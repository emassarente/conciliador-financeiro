# =============================================================================
# GERENCIADOR DE BANCO DE DADOS - SQLite
# Armazena histórico de lançamentos do Razão e Extrato por até 3 anos.
# Nenhum dado é apagado — cada importação é registrada com data/hora.
# Consultas de pendências ficam disponíveis por todo o período retido.
# =============================================================================

import sqlite3
import hashlib
import logging
import pandas as pd
from pathlib import Path
from datetime import datetime, date
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# Caminho padrão do banco (dentro da pasta do projeto)
DB_PATH_PADRAO = Path(__file__).parent / "conciliacao.db"


class DatabaseManager:
    """
    Gerencia o banco SQLite de histórico de conciliação.

    Tabelas:
        importacoes   — log de cada arquivo importado
        razao         — todos os lançamentos do Razão (nunca apagados)
        extrato       — todos os lançamentos do Extrato (nunca apagados)
        conciliacoes  — resultado de cada rodada de conciliação

    Retenção: lançamentos ficam disponíveis por 3 anos a partir da data do lançamento.
    """

    SCHEMA = """
    -- Escritório de contabilidade (operador do sistema — ex: Lage Contabilidade)
    CREATE TABLE IF NOT EXISTS escritorio (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        nome          TEXT NOT NULL,
        cnpj          TEXT,
        responsavel   TEXT,
        telefone      TEXT,
        email         TEXT,
        criado_em     DATETIME DEFAULT (datetime('now','localtime'))
    );

    -- Clientes atendidos pelo escritório (ex: Afrika, IGP, etc.)
    CREATE TABLE IF NOT EXISTS clientes (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        nome          TEXT NOT NULL,
        cnpj          TEXT UNIQUE,
        codigo        TEXT,
        responsavel   TEXT,
        ativo         INTEGER DEFAULT 1,
        criado_em     DATETIME DEFAULT (datetime('now','localtime'))
    );

    -- Log de importações
    CREATE TABLE IF NOT EXISTS importacoes (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo          TEXT NOT NULL,          -- 'RAZAO' ou 'EXTRATO'
        arquivo       TEXT NOT NULL,
        empresa       TEXT,
        cnpj          TEXT,
        periodo_ini   DATE,
        periodo_fim   DATE,
        total_linhas  INTEGER,
        cliente_id    INTEGER REFERENCES clientes(id),
        importado_em  DATETIME DEFAULT (datetime('now','localtime'))
    );

    -- Lançamentos do Razão
    CREATE TABLE IF NOT EXISTS razao (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        importacao_id   INTEGER REFERENCES importacoes(id),
        empresa         TEXT,
        cnpj            TEXT,
        conta_codigo    TEXT,
        conta_nome      TEXT,
        data_lancamento DATE NOT NULL,
        lote            TEXT,
        historico       TEXT,
        cta_contrapartida TEXT,
        debito          REAL DEFAULT 0,
        credito         REAL DEFAULT 0,
        valor           REAL NOT NULL,
        saldo           REAL DEFAULT 0,
        saldo_exercicio REAL DEFAULT 0,
        importado_em    DATETIME DEFAULT (datetime('now','localtime')),
        cliente_id      INTEGER REFERENCES clientes(id),
        hash_linha      TEXT
    );

    -- Lançamentos do Extrato Bancário
    CREATE TABLE IF NOT EXISTS extrato (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        importacao_id   INTEGER REFERENCES importacoes(id),
        data_lancamento DATE NOT NULL,
        descricao       TEXT,
        valor           REAL NOT NULL,
        saldo           REAL DEFAULT 0,
        documento       TEXT,
        importado_em    DATETIME DEFAULT (datetime('now','localtime')),
        cliente_id      INTEGER REFERENCES clientes(id),
        banco           TEXT,
        agencia         TEXT,
        conta           TEXT,
        hash_linha      TEXT
    );

    -- Resultados de conciliação
    CREATE TABLE IF NOT EXISTS conciliacoes (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        razao_id        INTEGER REFERENCES razao(id),
        extrato_id      INTEGER REFERENCES extrato(id),
        status          TEXT NOT NULL,
        tipo_match      TEXT,
        confidence      REAL,
        observacoes     TEXT,
        conciliado_em   DATETIME DEFAULT (datetime('now','localtime')),
        cliente_id      INTEGER REFERENCES clientes(id),
        conciliado_por  TEXT DEFAULT 'AUTO'
    );

    -- Padrões aprendidos pelo modelo ML
    CREATE TABLE IF NOT EXISTS padroes_aprendidos (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        historico_razao     TEXT NOT NULL,
        descricao_extrato   TEXT NOT NULL,
        tipo_match          TEXT NOT NULL,
        confirmado_por      TEXT DEFAULT 'AUTO',
        frequencia          INTEGER DEFAULT 1,
        ultima_ocorrencia   DATE,
        cliente_id          INTEGER REFERENCES clientes(id),
        criado_em           DATETIME DEFAULT (datetime('now','localtime'))
    );

    -- Inteligência global (sem dados financeiros, sem empresa_id)
    -- Armazena APENAS padrões de texto, nunca valores ou documentos de empresas
    CREATE TABLE IF NOT EXISTS global_learning (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        pattern_type        TEXT NOT NULL,     -- 'RAZAO_EXTRATO', 'RAZAO_KEYWORD', 'EXTRATO_KEYWORD'
        pattern_text        TEXT NOT NULL,     -- texto normalizado do padrão (sem dados financeiros)
        match_target        TEXT,              -- texto do alvo do match (lado extrato)
        similarity_score    REAL DEFAULT 0.0,  -- score médio de similaridade nos matches
        match_success_rate  REAL DEFAULT 1.0,  -- taxa de sucesso (0.0-1.0)
        usage_count         INTEGER DEFAULT 1, -- quantas vezes foi usado com sucesso
        last_seen           DATETIME DEFAULT (datetime('now','localtime')),
        criado_em           DATETIME DEFAULT (datetime('now','localtime'))
    );

    -- Índices para performance
    CREATE INDEX IF NOT EXISTS idx_razao_data      ON razao(data_lancamento);
    CREATE INDEX IF NOT EXISTS idx_razao_conta     ON razao(conta_codigo);
    CREATE INDEX IF NOT EXISTS idx_razao_hash      ON razao(hash_linha);
    CREATE INDEX IF NOT EXISTS idx_razao_cliente   ON razao(cliente_id);
    CREATE INDEX IF NOT EXISTS idx_extrato_data    ON extrato(data_lancamento);
    CREATE INDEX IF NOT EXISTS idx_extrato_hash    ON extrato(hash_linha);
    CREATE INDEX IF NOT EXISTS idx_extrato_cliente ON extrato(cliente_id);
    CREATE INDEX IF NOT EXISTS idx_padroes_hist    ON padroes_aprendidos(historico_razao);
    CREATE INDEX IF NOT EXISTS idx_padroes_desc    ON padroes_aprendidos(descricao_extrato);
    CREATE INDEX IF NOT EXISTS idx_global_pattern  ON global_learning(pattern_text);
    CREATE INDEX IF NOT EXISTS idx_global_type     ON global_learning(pattern_type);

    -- Usuários do sistema
    CREATE TABLE IF NOT EXISTS usuarios (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        email         TEXT NOT NULL UNIQUE,
        nome          TEXT NOT NULL,
        senha_hash    TEXT NOT NULL,
        perfil        TEXT NOT NULL DEFAULT 'usuario',  -- 'igp' | 'gerente' | 'usuario'
        escritorio_id INTEGER REFERENCES escritorio(id),
        ativo         INTEGER DEFAULT 1,
        criado_em     DATETIME DEFAULT (datetime('now','localtime')),
        ultimo_acesso DATETIME
    );

    -- Vínculo usuário ↔ empresas permitidas (só para perfil 'usuario')
    CREATE TABLE IF NOT EXISTS usuario_empresas (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id  INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        cliente_id  INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
        UNIQUE(usuario_id, cliente_id)
    );

    CREATE INDEX IF NOT EXISTS idx_usuarios_email     ON usuarios(email);
    CREATE INDEX IF NOT EXISTS idx_usuarios_escrit    ON usuarios(escritorio_id);
    CREATE INDEX IF NOT EXISTS idx_usu_emp_usuario    ON usuario_empresas(usuario_id);

    -- Vínculo contabilidade (escritorio) ↔ empresas (clientes)
    CREATE TABLE IF NOT EXISTS escritorio_clientes (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        escritorio_id INTEGER NOT NULL REFERENCES escritorio(id) ON DELETE CASCADE,
        cliente_id    INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
        UNIQUE(escritorio_id, cliente_id)
    );
    CREATE INDEX IF NOT EXISTS idx_esc_cli_escrit ON escritorio_clientes(escritorio_id);
    CREATE INDEX IF NOT EXISTS idx_esc_cli_client ON escritorio_clientes(cliente_id);
    """

    def __init__(self, db_path: Path = None):
        self.db_path = Path(db_path) if db_path else DB_PATH_PADRAO
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._criar_schema()
        self._migrar_schema()
        self.seed_usuarios_iniciais()
        logger.info(f"💾 Banco de dados: {self.db_path}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _criar_schema(self):
        """Cria as tabelas se ainda não existirem."""
        with self._conn() as conn:
            for stmt in self.SCHEMA.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    try:
                        conn.execute(stmt)
                    except sqlite3.OperationalError:
                        # Ignora erros em índices sobre colunas ainda inexistentes
                        # (serão criados após _migrar_schema)
                        pass

    def _migrar_schema(self):
        """Migra bancos existentes sem destruir dados."""
        with self._conn() as conn:
            # 1. Renomeia tabela empresas → clientes (se ainda existir com nome antigo)
            tabelas = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            if "empresas" in tabelas and "clientes" not in tabelas:
                conn.execute("ALTER TABLE empresas RENAME TO clientes")

            # 2. Adiciona colunas novas (opera tanto em bancos novos quanto antigos)
            migracoes = [
                ("importacoes",        "cliente_id",  "INTEGER"),
                ("importacoes",        "empresa_id",  "INTEGER"),  # retrocompat.
                ("razao",              "cliente_id",  "INTEGER"),
                ("razao",              "empresa_id",  "INTEGER"),  # retrocompat.
                ("extrato",            "cliente_id",  "INTEGER"),
                ("extrato",            "empresa_id",  "INTEGER"),  # retrocompat.
                ("extrato",            "banco",        "TEXT"),
                ("extrato",            "agencia",      "TEXT"),
                ("extrato",            "conta",        "TEXT"),
                ("conciliacoes",       "cliente_id",  "INTEGER"),
                ("conciliacoes",       "empresa_id",  "INTEGER"),  # retrocompat.
                ("padroes_aprendidos", "cliente_id",  "INTEGER"),
                ("padroes_aprendidos", "empresa_id",  "INTEGER"),  # retrocompat.
                ("clientes",           "responsavel", "TEXT"),
            ]
            for tabela, coluna, tipo in migracoes:
                try:
                    conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
                except sqlite3.OperationalError:
                    pass

            # 3. Copia empresa_id → cliente_id onde cliente_id ainda está NULL
            for tabela in ("importacoes", "razao", "extrato", "conciliacoes", "padroes_aprendidos"):
                try:
                    conn.execute(
                        f"UPDATE {tabela} SET cliente_id = empresa_id "
                        f"WHERE cliente_id IS NULL AND empresa_id IS NOT NULL"
                    )
                except sqlite3.OperationalError:
                    pass

            # 4a. Colunas extras na tabela razao (para módulo Razão Contábil)
            for _col_sql in [
                "ALTER TABLE razao ADD COLUMN modulo TEXT DEFAULT 'CONCILIACAO'",
                "ALTER TABLE razao ADD COLUMN saldo_anterior REAL DEFAULT 0.0",
                "ALTER TABLE razao ADD COLUMN conta_reduzida TEXT DEFAULT ''",
            ]:
                try:
                    conn.execute(_col_sql)
                except sqlite3.OperationalError:
                    pass

            # 4. Índices pós-migração
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS idx_razao_cliente   ON razao(cliente_id)",
                "CREATE INDEX IF NOT EXISTS idx_extrato_cliente ON extrato(cliente_id)",
            ]:
                try:
                    conn.execute(idx_sql)
                except sqlite3.OperationalError:
                    pass

            # 5a. Cria tabela razao_conciliacao_manual
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS razao_conciliacao_manual (
                        id            INTEGER PRIMARY KEY AUTOINCREMENT,
                        cliente_id    INTEGER NOT NULL,
                        conta_codigo  TEXT    NOT NULL,
                        conta_reduzida TEXT   DEFAULT '',
                        linha_idx     INTEGER NOT NULL,
                        criado_em     DATETIME DEFAULT (datetime('now','localtime'))
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_razao_manual_cliente "
                    "ON razao_conciliacao_manual(cliente_id)"
                )
            except sqlite3.OperationalError:
                pass

            # 5b. Cria tabela global_learning se ainda não existir (banco antigo)
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS global_learning (
                        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                        pattern_type        TEXT NOT NULL,
                        pattern_text        TEXT NOT NULL,
                        match_target        TEXT,
                        similarity_score    REAL DEFAULT 0.0,
                        match_success_rate  REAL DEFAULT 1.0,
                        usage_count         INTEGER DEFAULT 1,
                        last_seen           DATETIME DEFAULT (datetime('now','localtime')),
                        criado_em           DATETIME DEFAULT (datetime('now','localtime'))
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_global_pattern ON global_learning(pattern_text)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_global_type ON global_learning(pattern_type)"
                )
            except sqlite3.OperationalError:
                pass

            # 5c. Cria tabelas de autenticação e vínculos em bancos já existentes
            for _sql_auth in [
                """CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    nome TEXT NOT NULL,
                    senha_hash TEXT NOT NULL,
                    perfil TEXT NOT NULL DEFAULT 'usuario',
                    escritorio_id INTEGER REFERENCES escritorio(id),
                    ativo INTEGER DEFAULT 1,
                    criado_em DATETIME DEFAULT (datetime('now','localtime')),
                    ultimo_acesso DATETIME
                )""",
                """CREATE TABLE IF NOT EXISTS usuario_empresas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
                    UNIQUE(usuario_id, cliente_id)
                )""",
                "CREATE INDEX IF NOT EXISTS idx_usuarios_email ON usuarios(email)",
                "CREATE INDEX IF NOT EXISTS idx_usu_emp_usuario ON usuario_empresas(usuario_id)",
                """CREATE TABLE IF NOT EXISTS escritorio_clientes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    escritorio_id INTEGER NOT NULL REFERENCES escritorio(id) ON DELETE CASCADE,
                    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
                    UNIQUE(escritorio_id, cliente_id)
                )""",
                "CREATE INDEX IF NOT EXISTS idx_esc_cli_escrit ON escritorio_clientes(escritorio_id)",
                "CREATE INDEX IF NOT EXISTS idx_esc_cli_client ON escritorio_clientes(cliente_id)",
            ]:
                try:
                    conn.execute(_sql_auth)
                except sqlite3.OperationalError:
                    pass

            # 5. Repara conciliacoes com extrato_id NULL (hash não bateu na gravação)
            #    Tenta preencher via JOIN data_lancamento + valor do razao → extrato
            try:
                conn.execute("""
                    UPDATE conciliacoes
                    SET extrato_id = (
                        SELECT e.id FROM extrato e
                        JOIN razao r ON r.id = conciliacoes.razao_id
                        WHERE e.data_lancamento = r.data_lancamento
                          AND ABS(e.valor - r.valor) < 0.01
                          AND (e.cliente_id = conciliacoes.cliente_id
                               OR e.cliente_id IS NULL
                               OR conciliacoes.cliente_id IS NULL)
                        ORDER BY e.id
                        LIMIT 1
                    )
                    WHERE extrato_id IS NULL
                      AND razao_id IS NOT NULL
                """)
            except sqlite3.OperationalError:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # GESTÃO DO ESCRITÓRIO (Lage Contabilidade)
    # ─────────────────────────────────────────────────────────────────────────

    def obter_escritorio(self) -> Optional[Dict]:
        """Retorna dados do escritório cadastrado (sempre o primeiro registro)."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM escritorio ORDER BY id LIMIT 1").fetchone()
            return dict(row) if row else None

    def salvar_escritorio(self, nome: str, cnpj: str = "",
                          responsavel: str = "", telefone: str = "",
                          email: str = ""):
        """Cria ou atualiza o escritório."""
        with self._conn() as conn:
            existente = conn.execute("SELECT id FROM escritorio LIMIT 1").fetchone()
            if existente:
                conn.execute(
                    """UPDATE escritorio SET nome=?, cnpj=?, responsavel=?,
                       telefone=?, email=? WHERE id=?""",
                    (nome, cnpj, responsavel, telefone, email, existente["id"])
                )
            else:
                conn.execute(
                    """INSERT INTO escritorio(nome, cnpj, responsavel, telefone, email)
                       VALUES (?,?,?,?,?)""",
                    (nome, cnpj, responsavel, telefone, email)
                )

    # ─────────────────────────────────────────────────────────────────────────
    # GESTÃO DE CLIENTES
    # ─────────────────────────────────────────────────────────────────────────

    def criar_cliente(self, nome: str, cnpj: str = "", codigo: str = "",
                      responsavel: str = "") -> int:
        """Cadastra novo cliente. Retorna o ID."""
        with self._conn() as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO clientes(nome, cnpj, codigo, responsavel) VALUES (?,?,?,?)",
                    (nome.strip(), cnpj.strip(), codigo.strip(), responsavel.strip())
                )
                return cur.lastrowid
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT id FROM clientes WHERE cnpj=?", (cnpj.strip(),)
                ).fetchone()
                return row["id"] if row else -1

    def get_or_create_cliente(self, nome: str, cnpj: str = "") -> int:
        """
        Busca cliente pelo CNPJ (ou nome se CNPJ vazio).
        Cria automaticamente se não existir.
        Retorna o ID do cliente.
        """
        cnpj_limpo = cnpj.strip() if cnpj else ""
        nome_limpo = nome.strip() if nome else ""
        with self._conn() as conn:
            # 1. Busca por CNPJ (mais confiável)
            if cnpj_limpo:
                row = conn.execute(
                    "SELECT id, nome FROM clientes WHERE cnpj=?", (cnpj_limpo,)
                ).fetchone()
                if row:
                    # Atualiza nome se estava vazio e agora temos um nome
                    if nome_limpo and not (row["nome"] or "").strip():
                        conn.execute(
                            "UPDATE clientes SET nome=? WHERE id=?",
                            (nome_limpo, row["id"])
                        )
                    return row["id"]
            # 2. Busca por nome exato
            if nome_limpo:
                row = conn.execute(
                    "SELECT id FROM clientes WHERE UPPER(nome)=UPPER(?)", (nome_limpo,)
                ).fetchone()
                if row:
                    return row["id"]
        # 3. Cria novo cliente
        return self.criar_cliente(nome_limpo, cnpj_limpo)

    def listar_clientes(self, apenas_ativos: bool = True) -> List[Dict]:
        """Retorna lista de clientes cadastrados."""
        sql = "SELECT * FROM clientes"
        if apenas_ativos:
            sql += " WHERE ativo=1"
        sql += " ORDER BY nome"
        with self._conn() as conn:
            rows = conn.execute(sql).fetchall()
            return [dict(r) for r in rows]

    def obter_cliente(self, cliente_id: int) -> Optional[Dict]:
        """Retorna dados de um cliente pelo ID."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM clientes WHERE id=?", (cliente_id,)
            ).fetchone()
            return dict(row) if row else None

    def atualizar_cliente(self, cliente_id: int, nome: str, cnpj: str = "",
                          codigo: str = "", responsavel: str = ""):
        """Atualiza dados de um cliente."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE clientes SET nome=?, cnpj=?, codigo=?, responsavel=? WHERE id=?",
                (nome.strip(), cnpj.strip(), codigo.strip(), responsavel.strip(), cliente_id)
            )

    def desativar_cliente(self, cliente_id: int):
        """Desativa um cliente (não apaga dados)."""
        with self._conn() as conn:
            conn.execute("UPDATE clientes SET ativo=0 WHERE id=?", (cliente_id,))

    def reativar_cliente(self, cliente_id: int):
        """Reativa um cliente."""
        with self._conn() as conn:
            conn.execute("UPDATE clientes SET ativo=1 WHERE id=?", (cliente_id,))

    # Aliases para retrocompatibilidade com código existente
    def criar_empresa(self, nome, cnpj="", codigo="") -> int:
        return self.criar_cliente(nome, cnpj, codigo)

    def listar_empresas(self, apenas_ativas=True) -> List[Dict]:
        return self.listar_clientes(apenas_ativas)

    def obter_empresa(self, empresa_id) -> Optional[Dict]:
        return self.obter_cliente(empresa_id)

    def atualizar_empresa(self, empresa_id, nome, cnpj="", codigo=""):
        self.atualizar_cliente(empresa_id, nome, cnpj, codigo)

    def desativar_empresa(self, empresa_id):
        self.desativar_cliente(empresa_id)

    # ─────────────────────────────────────────────────────────────────────────
    # IMPORTAÇÃO DO RAZÃO
    # ─────────────────────────────────────────────────────────────────────────

    def importar_razao(self, df: pd.DataFrame, arquivo: str,
                       empresa: str = "", cnpj: str = "",
                       periodo_ini=None, periodo_fim=None,
                       empresa_id: int = None,
                       cliente_id: int = None) -> int:
        """
        Insere lançamentos do Razão no banco.
        Lançamentos duplicados (mesmo hash) são ignorados automaticamente.

        Returns:
            ID da importação registrada
        """
        import hashlib

        with self._conn() as conn:
            # Registra a importação
            cur = conn.execute(
                """INSERT INTO importacoes(tipo, arquivo, empresa, cnpj,
                   periodo_ini, periodo_fim, total_linhas, cliente_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                ("RAZAO", arquivo, empresa, cnpj,
                 str(periodo_ini) if periodo_ini else None,
                 str(periodo_fim) if periodo_fim else None,
                 len(df), cliente_id or empresa_id)
            )
            importacao_id = cur.lastrowid

            inseridos = 0
            duplicados = 0

            for _, row in df.iterrows():
                # Hash para detectar duplicatas
                chave = f"{row.get('data_razao')}|{row.get('historico','')}|{row.get('valor_razao',0)}"
                hash_linha = hashlib.md5(chave.encode()).hexdigest()

                # Verifica se já existe
                existe = conn.execute(
                    "SELECT 1 FROM razao WHERE hash_linha=?", (hash_linha,)
                ).fetchone()

                if existe:
                    duplicados += 1
                    continue

                data = row.get("data_razao")
                if hasattr(data, "date"):
                    data = data.date()

                conn.execute(
                    """INSERT INTO razao(importacao_id, empresa, cnpj,
                       conta_codigo, conta_nome, data_lancamento, lote,
                       historico, cta_contrapartida, debito, credito,
                       valor, saldo, saldo_exercicio, hash_linha, cliente_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (importacao_id, empresa, cnpj,
                     row.get("conta_codigo", ""),
                     row.get("conta_nome", ""),
                     str(data) if data else None,
                     row.get("lote", ""),
                     row.get("historico", ""),
                     row.get("cta_contrapartida", ""),
                     float(row.get("debito", 0) or 0),
                     float(row.get("credito", 0) or 0),
                     float(row.get("valor_razao", 0) or 0),
                     float(row.get("saldo", 0) or 0),
                     float(row.get("saldo_exercicio", 0) or 0),
                     hash_linha, cliente_id or empresa_id)
                )
                inseridos += 1

        logger.info(f"✅ Razão: {inseridos} inseridos, {duplicados} duplicatas ignoradas")
        return importacao_id

    # ─────────────────────────────────────────────────────────────────────────
    # IMPORTAÇÃO DO EXTRATO
    # ─────────────────────────────────────────────────────────────────────────

    def importar_extrato(self, df: pd.DataFrame, arquivo: str,
                        empresa_id: int = None, banco: str = "",
                        agencia: str = "", conta: str = "",
                        cliente_id: int = None) -> int:
        """
        Insere lançamentos do Extrato no banco.
        Lançamentos duplicados (mesmo hash) são ignorados automaticamente.
        """
        import hashlib

        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO importacoes(tipo, arquivo, total_linhas, cliente_id)
                   VALUES (?,?,?,?)""",
                ("EXTRATO", arquivo, len(df), cliente_id or empresa_id)
            )
            importacao_id = cur.lastrowid

            inseridos = 0
            duplicados = 0

            for _, row in df.iterrows():
                # Parser produces 'descricao'; fallback to 'descricao_extrato'
                desc = row.get("descricao") or row.get("descricao_extrato") or ""
                data_e = row.get("data_extrato") or row.get("data_lancamento") or ""
                valor_e = row.get("valor_extrato") or row.get("valor") or 0

                chave = f"{data_e}|{desc}|{valor_e}"
                hash_linha = hashlib.md5(chave.encode()).hexdigest()

                existe = conn.execute(
                    "SELECT 1 FROM extrato WHERE hash_linha=?", (hash_linha,)
                ).fetchone()

                if existe:
                    duplicados += 1
                    continue

                data = data_e
                if hasattr(data, "date"):
                    data = data.date()

                conn.execute(
                    """INSERT INTO extrato(importacao_id, data_lancamento,
                       descricao, valor, saldo, documento, hash_linha,
                       cliente_id, banco, agencia, conta)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (importacao_id,
                     str(data) if data else None,
                     str(desc),
                     float(valor_e or 0),
                     float(row.get("saldo", 0) or 0),
                     row.get("documento", ""),
                     hash_linha, cliente_id or empresa_id, banco, agencia, conta)
                )
                inseridos += 1

        logger.info(f"✅ Extrato: {inseridos} inseridos, {duplicados} duplicatas ignoradas")
        return importacao_id

    # ─────────────────────────────────────────────────────────────────────────
    # CONSULTAS
    # ─────────────────────────────────────────────────────────────────────────

    def consultar_razao(self, data_ini=None, data_fim=None,
                        conta: str = None,
                        empresa_id: int = None,
                        cliente_id: int = None) -> pd.DataFrame:
        """Retorna lançamentos do Razão com filtros opcionais."""
        sql = "SELECT * FROM razao WHERE 1=1"
        params = []
        cid = cliente_id or empresa_id
        if cid:
            sql += " AND cliente_id=?"; params.append(cid)
        if data_ini:
            sql += " AND data_lancamento >= ?"; params.append(str(data_ini))
        if data_fim:
            sql += " AND data_lancamento <= ?"; params.append(str(data_fim))
        if conta:
            sql += " AND (conta_codigo LIKE ? OR conta_nome LIKE ?)";
            params += [f"%{conta}%", f"%{conta}%"]
        sql += " ORDER BY data_lancamento, id"
        with self._conn() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def consultar_extrato(self, data_ini=None, data_fim=None,
                          empresa_id: int = None,
                          cliente_id: int = None) -> pd.DataFrame:
        """Retorna lançamentos do Extrato com filtros opcionais."""
        sql = "SELECT * FROM extrato WHERE 1=1"
        params = []
        cid = cliente_id or empresa_id
        if cid:
            sql += " AND cliente_id=?"; params.append(cid)
        if data_ini:
            sql += " AND data_lancamento >= ?"; params.append(str(data_ini))
        if data_fim:
            sql += " AND data_lancamento <= ?"; params.append(str(data_fim))
        sql += " ORDER BY data_lancamento, id"
        with self._conn() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def consultar_extrato_pendente(self, cliente_id: int = None) -> pd.DataFrame:
        """Retorna lançamentos do Extrato que NÃO possuem conciliação registrada."""
        params = []
        sql = """
            SELECT e.*
            FROM extrato e
            WHERE NOT EXISTS (
                SELECT 1 FROM conciliacoes c
                WHERE c.extrato_id = e.id
            )
        """
        cid = cliente_id
        if cid:
            sql += " AND e.cliente_id = ?"
            params.append(cid)
        sql += " ORDER BY e.data_lancamento, e.id"
        with self._conn() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def historico_importacoes(self) -> pd.DataFrame:
        """Lista todas as importações registradas."""
        with self._conn() as conn:
            return pd.read_sql_query(
                "SELECT * FROM importacoes ORDER BY importado_em DESC", conn
            )

    def estatisticas(self, empresa_id: int = None, cliente_id: int = None) -> dict:
        """Retorna estatísticas gerais do banco, opcionalmente por cliente."""
        cid = cliente_id or empresa_id
        filtro = " WHERE cliente_id=?" if cid else ""
        p = (cid,) if cid else ()
        with self._conn() as conn:
            total_razao   = conn.execute(f"SELECT COUNT(*) FROM razao{filtro}", p).fetchone()[0]
            total_extrato = conn.execute(f"SELECT COUNT(*) FROM extrato{filtro}", p).fetchone()[0]
            total_conc    = conn.execute(f"SELECT COUNT(*) FROM conciliacoes{filtro}", p).fetchone()[0]
            # Pendentes = lançamentos Razão sem nenhuma conciliação
            pend_sql = (
                "SELECT COUNT(*) FROM razao r WHERE NOT EXISTS "
                "(SELECT 1 FROM conciliacoes c WHERE c.razao_id = r.id)"
                + (" AND r.cliente_id=?" if cid else "")
            )
            pendentes_razao = conn.execute(pend_sql, p).fetchone()[0]
            ultima_imp    = conn.execute(
                "SELECT MAX(importado_em) FROM importacoes" +
                (" WHERE cliente_id=?" if cid else ""), p
            ).fetchone()[0]
            contas = conn.execute(
                "SELECT DISTINCT conta_codigo, conta_nome FROM razao" +
                filtro + " ORDER BY conta_codigo", p
            ).fetchall()
        return {
            "total_razao":        total_razao,
            "total_extrato":      total_extrato,
            "total_conciliacoes": total_conc,
            "pendentes_razao":    pendentes_razao,
            "ultima_importacao":  ultima_imp,
            "contas": [dict(c) for c in contas],
        }

    def dashboard_mensal(self, empresa_id: int = None, cliente_id: int = None) -> pd.DataFrame:
        """
        Retorna resumo mensal de conciliações para gráficos do dashboard.
        Agrega por mês: total lançamentos razão, extrato, conciliados, pendentes.
        """
        cid = cliente_id or empresa_id
        filtro = " AND r.cliente_id=?" if cid else ""
        p = (cid,) if cid else ()
        sql = f"""
            SELECT
                strftime('%Y-%m', r.data_lancamento) AS mes,
                COUNT(DISTINCT r.id)                 AS total_razao,
                COUNT(DISTINCT c.razao_id)            AS conciliados,
                COUNT(DISTINCT r.id) - COUNT(DISTINCT c.razao_id) AS pendentes,
                COALESCE(SUM(r.valor), 0)            AS valor_total,
                COALESCE(SUM(CASE WHEN c.id IS NOT NULL THEN r.valor ELSE 0 END), 0) AS valor_conciliado
            FROM razao r
            LEFT JOIN conciliacoes c ON c.razao_id = r.id
            WHERE r.data_lancamento IS NOT NULL {filtro}
            GROUP BY mes
            ORDER BY mes
        """
        with self._conn() as conn:
            return pd.read_sql_query(sql, conn, params=p)

    def dashboard_por_status(self, empresa_id: int = None, cliente_id: int = None) -> pd.DataFrame:
        """Retorna contagem de lançamentos por status de conciliação."""
        cid = cliente_id or empresa_id
        filtro = " AND r.cliente_id=?" if cid else ""
        p = (cid,) if cid else ()
        sql = f"""
            SELECT
                COALESCE(c.status, 'NAO_CONCILIADO') AS status,
                COUNT(*) AS total,
                COALESCE(SUM(r.valor), 0) AS valor
            FROM razao r
            LEFT JOIN conciliacoes c ON c.razao_id = r.id
            WHERE 1=1 {filtro}
            GROUP BY status
        """
        with self._conn() as conn:
            return pd.read_sql_query(sql, conn, params=p)

    def dashboard_por_banco(self, empresa_id: int = None, cliente_id: int = None) -> pd.DataFrame:
        """Retorna lançamentos de extrato agrupados por banco."""
        cid = cliente_id or empresa_id
        filtro = " WHERE cliente_id=?" if cid else ""
        p = (cid,) if cid else ()
        sql = f"""
            SELECT
                COALESCE(banco, 'Não identificado') AS banco,
                COUNT(*) AS total_lancamentos,
                SUM(CASE WHEN valor > 0 THEN valor ELSE 0 END) AS total_credito,
                SUM(CASE WHEN valor < 0 THEN ABS(valor) ELSE 0 END) AS total_debito
            FROM extrato {filtro}
            GROUP BY banco
            ORDER BY total_lancamentos DESC
        """
        with self._conn() as conn:
            return pd.read_sql_query(sql, conn, params=p)

    # ─────────────────────────────────────────────────────────────────────────
    # SALVAR RESULTADOS DE CONCILIAÇÃO
    # ─────────────────────────────────────────────────────────────────────────

    def salvar_conciliacoes(self, df_resultado: pd.DataFrame,
                            cliente_id: int = None) -> int:
        """
        Persiste o resultado de uma rodada de conciliação na tabela conciliacoes.
        Faz match por hash de data+valor+historico para encontrar os IDs no banco.
        Retorna quantidade de registros salvos.
        """
        import hashlib

        salvos = 0
        with self._conn() as conn:
            for _, row in df_resultado.iterrows():
                status = str(row.get("status", "") or "")
                if status == "NAO_CONCILIADO" or not status:
                    continue

                # Encontra razao_id pelo hash da linha
                data_r  = str(row.get("data_razao", "") or "")
                hist_r  = str(row.get("historico_razao", "") or "")
                valor_r = row.get("valor_razao", 0) or 0
                hash_r  = hashlib.md5(f"{data_r}|{hist_r}|{valor_r}".encode()).hexdigest()

                r_row = conn.execute(
                    "SELECT id FROM razao WHERE hash_linha=? LIMIT 1", (hash_r,)
                ).fetchone()
                # fallback: busca por data+historico+valor sem hash
                if not r_row:
                    r_row = conn.execute(
                        "SELECT id FROM razao WHERE data_lancamento=? AND historico=? AND ABS(valor-?)<0.01"
                        " AND (cliente_id=? OR cliente_id IS NULL) LIMIT 1",
                        (data_r, hist_r, float(valor_r), cliente_id)
                    ).fetchone()
                razao_id = r_row["id"] if r_row else None

                # Encontra extrato_id — tenta hash primeiro, depois data+valor (descricao pode estar vazia)
                data_e  = str(row.get("data_extrato", "") or "")
                desc_e  = str(row.get("descricao_extrato", "") or "")
                valor_e = row.get("valor_extrato", 0) or 0
                hash_e  = hashlib.md5(f"{data_e}|{desc_e}|{valor_e}".encode()).hexdigest()

                e_row = conn.execute(
                    "SELECT id FROM extrato WHERE hash_linha=? LIMIT 1", (hash_e,)
                ).fetchone()
                # fallback: busca por data+valor (independe de descricao)
                if not e_row and data_e and valor_e:
                    e_row = conn.execute(
                        "SELECT id FROM extrato WHERE data_lancamento=? AND ABS(valor-?)<0.01"
                        " AND (cliente_id=? OR cliente_id IS NULL) LIMIT 1",
                        (data_e, float(valor_e), cliente_id)
                    ).fetchone()
                extrato_id = e_row["id"] if e_row else None

                # Evita duplicata
                ja_existe = conn.execute(
                    "SELECT id FROM conciliacoes WHERE razao_id=? AND extrato_id=?",
                    (razao_id, extrato_id)
                ).fetchone() if razao_id and extrato_id else None

                if ja_existe:
                    continue

                conciliado_por = "MANUAL" if status == "MANUAL_CONCILIADO" else "AUTO"
                conn.execute(
                    """INSERT INTO conciliacoes
                       (razao_id, extrato_id, status, tipo_match, confidence,
                        observacoes, cliente_id, conciliado_por)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (razao_id, extrato_id, status,
                     str(row.get("tipo_match", "") or ""),
                     float(row.get("confidence", 0) or 0),
                     str(row.get("observacoes", "") or ""),
                     cliente_id,
                     conciliado_por)
                )
                salvos += 1

        logger.info(f"✅ Conciliações salvas: {salvos}")
        return salvos

    # ─────────────────────────────────────────────────────────────────────────
    # APRENDIZADO ML
    # ─────────────────────────────────────────────────────────────────────────

    def registrar_padrao(self, historico_razao: str, descricao_extrato: str,
                         tipo_match: str, confirmado_por: str = "AUTO",
                         data_ocorrencia=None):
        """
        Registra ou incrementa um par (razão ↔ extrato) confirmado.
        Se o par já existe, incrementa a frequência.
        """
        hist_norm = str(historico_razao).upper().strip()
        desc_norm = str(descricao_extrato).upper().strip()
        data_str  = str(data_ocorrencia) if data_ocorrencia else str(date.today())

        with self._conn() as conn:
            existe = conn.execute(
                """SELECT id, frequencia FROM padroes_aprendidos
                   WHERE historico_razao=? AND descricao_extrato=?""",
                (hist_norm, desc_norm)
            ).fetchone()

            if existe:
                conn.execute(
                    """UPDATE padroes_aprendidos
                       SET frequencia=?, ultima_ocorrencia=?, confirmado_por=?
                       WHERE id=?""",
                    (existe["frequencia"] + 1, data_str, confirmado_por, existe["id"])
                )
            else:
                conn.execute(
                    """INSERT INTO padroes_aprendidos
                       (historico_razao, descricao_extrato, tipo_match,
                        confirmado_por, frequencia, ultima_ocorrencia)
                       VALUES (?,?,?,?,1,?)""",
                    (hist_norm, desc_norm, tipo_match, confirmado_por, data_str)
                )

    def registrar_padroes_batch(self, df_resultado: pd.DataFrame,
                                confirmado_por: str = "AUTO"):
        """
        Registra todos os pares conciliados de um DataFrame de resultado.
        Chame após cada rodada de conciliação.
        """
        status_validos = {"CONCILIADO", "MATCH_COMBINADO", "MATCH_SIMILARIDADE",
                          "MANUAL_CONCILIADO"}
        for _, row in df_resultado.iterrows():
            if row.get("status") not in status_validos:
                continue
            hist  = str(row.get("historico_razao", "") or "").strip()
            desc  = str(row.get("descricao_extrato", "") or "").strip()
            if not hist or not desc or hist == "-" or desc == "-":
                continue
            self.registrar_padrao(
                historico_razao   = hist,
                descricao_extrato = desc,
                tipo_match        = str(row.get("tipo_match", "AUTO")),
                confirmado_por    = confirmado_por,
                data_ocorrencia   = row.get("data_razao") or row.get("data_extrato"),
            )

    def obter_padroes(self, min_frequencia: int = 1) -> pd.DataFrame:
        """
        Retorna todos os padrões aprendidos com frequência >= min_frequencia.
        Usado pelo LearningMatch para treinar o modelo.
        """
        with self._conn() as conn:
            return pd.read_sql_query(
                """SELECT historico_razao, descricao_extrato, tipo_match,
                          confirmado_por, frequencia, ultima_ocorrencia
                   FROM padroes_aprendidos
                   WHERE frequencia >= ?
                   ORDER BY frequencia DESC""",
                conn, params=(min_frequencia,)
            )

    def total_padroes(self) -> int:
        """Retorna quantidade total de padrões armazenados."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM padroes_aprendidos"
            ).fetchone()[0]

    # ─────────────────────────────────────────────────────────────────────────
    # APRENDIZADO GLOBAL (sem empresa_id — inteligência compartilhada)
    # Armazena APENAS padrões de texto. Nunca valores financeiros ou documentos.
    # ─────────────────────────────────────────────────────────────────────────

    def registrar_padrao_global(self, pattern_text: str, match_target: str,
                                pattern_type: str = "RAZAO_EXTRATO",
                                similarity_score: float = 1.0):
        """
        Registra ou incrementa um padrão global de match.
        Chamado automaticamente após cada match confirmado (qualquer empresa).
        Nunca grava valores financeiros — apenas textos normalizados.
        """
        import unicodedata as _ud, re as _re

        def _norm(t):
            t = _ud.normalize("NFKD", str(t or ""))
            t = "".join(c for c in t if not _ud.combining(c))
            t = t.upper()
            t = _re.sub(r"[^A-Z0-9 ]", " ", t)
            return _re.sub(r"\s+", " ", t).strip()

        pt = _norm(pattern_text)
        mt = _norm(match_target)
        if not pt or not mt:
            return

        with self._conn() as conn:
            row = conn.execute(
                """SELECT id, usage_count, similarity_score
                   FROM global_learning
                   WHERE pattern_type=? AND pattern_text=? AND match_target=?
                   LIMIT 1""",
                (pattern_type, pt, mt)
            ).fetchone()

            if row:
                # Atualiza média do score e incrementa uso
                n = row["usage_count"]
                novo_score = (row["similarity_score"] * n + similarity_score) / (n + 1)
                conn.execute(
                    """UPDATE global_learning
                       SET usage_count=?, similarity_score=?,
                           last_seen=datetime('now','localtime')
                       WHERE id=?""",
                    (n + 1, round(novo_score, 4), row["id"])
                )
            else:
                conn.execute(
                    """INSERT INTO global_learning
                       (pattern_type, pattern_text, match_target,
                        similarity_score, match_success_rate, usage_count)
                       VALUES (?,?,?,?,1.0,1)""",
                    (pattern_type, pt, mt, round(similarity_score, 4))
                )

    def obter_padroes_globais(self, min_uso: int = 2) -> pd.DataFrame:
        """
        Retorna padrões globais com usage_count >= min_uso.
        Usado pelo LearningMatch para complementar o score da empresa.
        """
        with self._conn() as conn:
            return pd.read_sql_query(
                """SELECT pattern_type, pattern_text, match_target,
                          similarity_score, match_success_rate, usage_count
                   FROM global_learning
                   WHERE usage_count >= ?
                   ORDER BY usage_count DESC, similarity_score DESC""",
                conn, params=(min_uso,)
            )

    def score_global(self, pattern_text: str, match_target: str,
                     pattern_type: str = "RAZAO_EXTRATO") -> float:
        """
        Retorna o score global para um par (pattern_text, match_target).
        Retorna 0.0 se não houver padrão registrado.
        """
        import unicodedata as _ud, re as _re

        def _norm(t):
            t = _ud.normalize("NFKD", str(t or ""))
            t = "".join(c for c in t if not _ud.combining(c))
            t = t.upper()
            t = _re.sub(r"[^A-Z0-9 ]", " ", t)
            return _re.sub(r"\s+", " ", t).strip()

        pt = _norm(pattern_text)
        mt = _norm(match_target)
        with self._conn() as conn:
            row = conn.execute(
                """SELECT similarity_score, usage_count FROM global_learning
                   WHERE pattern_type=? AND pattern_text=? AND match_target=?
                   LIMIT 1""",
                (pattern_type, pt, mt)
            ).fetchone()
        if not row:
            return 0.0
        # Penaliza padrões com poucos usos (confiança cresce com uso)
        uso_weight = min(row["usage_count"] / 10.0, 1.0)
        return round(row["similarity_score"] * uso_weight, 4)

    def registrar_padroes_globais_batch(self, df_resultado: pd.DataFrame):
        """
        Registra padrões globais a partir de um DataFrame de resultado.
        Chame junto com registrar_padroes_batch. Nunca grava valores.
        """
        status_validos = {"CONCILIADO", "MATCH_COMBINADO", "MATCH_APRENDIDO",
                          "MATCH_SIMILARIDADE", "MANUAL_CONCILIADO"}
        for _, row in df_resultado.iterrows():
            if row.get("status") not in status_validos:
                continue
            hist = str(row.get("historico_razao", "") or "").strip()
            desc = str(row.get("descricao_extrato", "") or "").strip()
            if not hist or not desc or hist == "-" or desc == "-":
                continue
            conf = float(row.get("confidence", 0) or 0) / 100.0
            self.registrar_padrao_global(
                pattern_text=hist,
                match_target=desc,
                pattern_type="RAZAO_EXTRATO",
                similarity_score=max(conf, 0.5),
            )

    def total_padroes_globais(self) -> int:
        """Retorna quantidade total de padrões globais."""
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM global_learning").fetchone()[0]

    # ─────────────────────────────────────────────────────────────────────────
    # EXPORTAÇÃO DE INSTÂNCIA POR EMPRESA
    # Gera um banco SQLite independente com dados da empresa + inteligência global
    # ─────────────────────────────────────────────────────────────────────────

    def export_company_instance(self, cliente_id: int, destino: Path = None) -> Path:
        """
        Gera uma cópia do banco contendo:
          - Dados APENAS da empresa (cliente_id)
          - Inteligência global completa (global_learning + padroes_aprendidos)
          - Cadastro da empresa (clientes)
          - SEM dados de outras empresas

        Args:
            cliente_id: ID da empresa a exportar
            destino: Path do arquivo .db de saída (padrão: pasta do banco atual)

        Returns:
            Path do arquivo gerado
        """
        import shutil

        cli = self.obter_cliente(cliente_id)
        if not cli:
            raise ValueError(f"Cliente {cliente_id} não encontrado.")

        nome_safe = "".join(c for c in cli["nome"] if c.isalnum() or c in " _-")
        nome_safe = nome_safe.strip().replace(" ", "_")[:40]
        if destino is None:
            destino = self.db_path.parent / f"export_{nome_safe}.db"

        # Cria banco de destino do zero
        if destino.exists():
            destino.unlink()

        dest_conn = sqlite3.connect(destino)
        dest_conn.row_factory = sqlite3.Row
        dest_conn.execute("PRAGMA journal_mode = WAL")

        with self._conn() as src:
            # 1. Recria schema completo no destino
            schema_stmts = src.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"
            ).fetchall()
            for stmt in schema_stmts:
                try:
                    dest_conn.execute(stmt[0])
                except Exception:
                    pass

            # 2. Copia dados da empresa
            tabelas_empresa = {
                "importacoes":        "cliente_id",
                "razao":              "cliente_id",
                "extrato":            "cliente_id",
                "conciliacoes":       "cliente_id",
                "padroes_aprendidos": "cliente_id",
            }
            for tabela, col_id in tabelas_empresa.items():
                try:
                    rows = src.execute(
                        f"SELECT * FROM {tabela} WHERE {col_id}=?", (cliente_id,)
                    ).fetchall()
                    if rows:
                        cols = rows[0].keys()
                        placeholders = ",".join("?" * len(cols))
                        dest_conn.executemany(
                            f"INSERT OR IGNORE INTO {tabela} ({','.join(cols)}) VALUES ({placeholders})",
                            [tuple(r) for r in rows]
                        )
                except Exception as e:
                    logger.warning(f"export {tabela}: {e}")

            # 3. Copia a empresa
            try:
                row = src.execute("SELECT * FROM clientes WHERE id=?", (cliente_id,)).fetchone()
                if row:
                    cols = row.keys()
                    placeholders = ",".join("?" * len(cols))
                    dest_conn.execute(
                        f"INSERT OR IGNORE INTO clientes ({','.join(cols)}) VALUES ({placeholders})",
                        tuple(row)
                    )
            except Exception as e:
                logger.warning(f"export clientes: {e}")

            # 4. Copia inteligência global completa
            try:
                rows = src.execute("SELECT * FROM global_learning").fetchall()
                if rows:
                    cols = rows[0].keys()
                    placeholders = ",".join("?" * len(cols))
                    dest_conn.executemany(
                        f"INSERT OR IGNORE INTO global_learning ({','.join(cols)}) VALUES ({placeholders})",
                        [tuple(r) for r in rows]
                    )
            except Exception as e:
                logger.warning(f"export global_learning: {e}")

            # 5. Copia padrões aprendidos globais (sem cliente_id ou de qualquer empresa)
            try:
                rows = src.execute(
                    "SELECT * FROM padroes_aprendidos WHERE cliente_id IS NULL"
                ).fetchall()
                if rows:
                    cols = rows[0].keys()
                    placeholders = ",".join("?" * len(cols))
                    dest_conn.executemany(
                        f"INSERT OR IGNORE INTO padroes_aprendidos ({','.join(cols)}) VALUES ({placeholders})",
                        [tuple(r) for r in rows]
                    )
            except Exception as e:
                logger.warning(f"export padroes globais: {e}")

        dest_conn.commit()
        dest_conn.close()
        logger.info(f"✅ Exportação concluída: {destino} ({destino.stat().st_size // 1024} KB)")
        return destino

    def limpar_antigos(self, anos: int = 3):
        """
        Remove lançamentos com mais de N anos (padrão 3).
        Chamado manualmente — nunca automático.
        """
        corte = date.today().replace(year=date.today().year - anos)
        with self._conn() as conn:
            conn.execute("DELETE FROM razao   WHERE data_lancamento < ?", (str(corte),))
            conn.execute("DELETE FROM extrato WHERE data_lancamento < ?", (str(corte),))
        logger.info(f"🗑️ Lançamentos anteriores a {corte} removidos do banco.")

    # ─────────────────────────────────────────────────────────────────────────
    # LIMPEZA DE DADOS DE UM CLIENTE
    # ─────────────────────────────────────────────────────────────────────────

    def consultar_lancamentos_emparelhados(self, data_ini=None, data_fim=None,
                                            banco: str = None,
                                            cliente_id: int = None) -> pd.DataFrame:
        """
        Retorna linhas emparelhadas para exibição no painel:
        - Par conciliado: razao + extrato na mesma linha
        - Só razão: extrato vazio (não conciliado)
        - Só extrato: razao vazio (não conciliado)
        """
        cid = cliente_id

        with self._conn() as conn:
            # 1. Pares conciliados
            sql_par = """
                SELECT c.status, c.confidence, c.tipo_match,
                       c.observacoes      AS observacoes,
                       r.id              AS razao_id,
                       r.data_lancamento AS data_razao,
                       r.historico       AS historico_razao,
                       r.valor           AS valor_razao,
                       e.id              AS extrato_id,
                       e.data_lancamento AS data_extrato,
                       e.descricao       AS descricao_extrato,
                       e.valor           AS valor_extrato,
                       e.banco           AS banco_extrato
                FROM conciliacoes c
                JOIN razao   r ON r.id = c.razao_id
                JOIN extrato e ON e.id = c.extrato_id
                WHERE 1=1
            """
            p_par = []
            if cid:
                sql_par += " AND r.cliente_id=? AND e.cliente_id=?"
                p_par += [cid, cid]
            if data_ini:
                sql_par += " AND r.data_lancamento >= ?"
                p_par.append(data_ini)
            if data_fim:
                sql_par += " AND r.data_lancamento <= ?"
                p_par.append(data_fim)
            if banco and banco != "Todos os bancos":
                sql_par += " AND e.banco=?"
                p_par.append(banco)

            df_par = pd.read_sql_query(sql_par, conn, params=p_par)

            # 2. Razão sem par
            sql_r = """
                SELECT 'NAO_CONCILIADO' AS status, 0 AS confidence, '' AS tipo_match,
                       NULL              AS observacoes,
                       r.id              AS razao_id,
                       r.data_lancamento AS data_razao,
                       r.historico       AS historico_razao,
                       r.valor           AS valor_razao,
                       NULL AS extrato_id,
                       NULL AS data_extrato,
                       NULL AS descricao_extrato,
                       NULL AS valor_extrato,
                       NULL AS banco_extrato
                FROM razao r
                WHERE NOT EXISTS (SELECT 1 FROM conciliacoes c2 WHERE c2.razao_id = r.id)
            """
            p_r = []
            if cid:
                sql_r += " AND r.cliente_id=?"
                p_r.append(cid)
            if data_ini:
                sql_r += " AND r.data_lancamento >= ?"
                p_r.append(data_ini)
            if data_fim:
                sql_r += " AND r.data_lancamento <= ?"
                p_r.append(data_fim)

            df_r = pd.read_sql_query(sql_r, conn, params=p_r)

            # 3. Extrato sem par
            sql_e = """
                SELECT 'NAO_CONCILIADO' AS status, 0 AS confidence, '' AS tipo_match,
                       NULL              AS observacoes,
                       NULL AS razao_id,
                       NULL AS data_razao,
                       NULL AS historico_razao,
                       NULL AS valor_razao,
                       e.id              AS extrato_id,
                       e.data_lancamento AS data_extrato,
                       e.descricao       AS descricao_extrato,
                       e.valor           AS valor_extrato,
                       e.banco           AS banco_extrato
                FROM extrato e
                WHERE NOT EXISTS (SELECT 1 FROM conciliacoes c2 WHERE c2.extrato_id = e.id)
            """
            p_e = []
            if cid:
                sql_e += " AND e.cliente_id=?"
                p_e.append(cid)
            if banco and banco != "Todos os bancos":
                sql_e += " AND e.banco=?"
                p_e.append(banco)

            df_e = pd.read_sql_query(sql_e, conn, params=p_e)

        df = pd.concat([df_par, df_r, df_e], ignore_index=True)
        if not df.empty:
            df["_sort"] = df["data_razao"].fillna(df["data_extrato"])
            df = df.sort_values("_sort").drop(columns=["_sort"])
        return df

    def registrar_conciliacao_manual(
        self,
        cliente_id: int,
        razao_id: int,
        extrato_id: int,
        valor_razao: float,
        valor_extrato: float,
        justificativa: str = "",
    ) -> int:
        """
        Registra uma conciliação feita manualmente pelo usuário.
        Se valores diferem, status = MANUAL_DIVERGENTE, senão MANUAL_CONCILIADO.
        Retorna o id da conciliação criada.
        """
        dif = abs(valor_razao - valor_extrato)
        status = "MANUAL_DIVERGENTE" if dif > 0.01 else "MANUAL_CONCILIADO"
        obs = justificativa or ("Conciliação manual" if dif <= 0.01 else
                                f"Divergência {dif:.2f}. {justificativa}")
        with self._conn() as conn:
            hist_r = ""
            desc_e = ""
            data_ref = None

            if razao_id:
                row_r = conn.execute(
                    "SELECT historico, data_lancamento FROM razao WHERE id=? LIMIT 1",
                    (razao_id,)
                ).fetchone()
                if row_r:
                    hist_r = str(row_r["historico"] or "").strip()
                    data_ref = row_r["data_lancamento"] or data_ref

            if extrato_id:
                row_e = conn.execute(
                    "SELECT descricao, data_lancamento FROM extrato WHERE id=? LIMIT 1",
                    (extrato_id,)
                ).fetchone()
                if row_e:
                    desc_e = str(row_e["descricao"] or "").strip()
                    data_ref = row_e["data_lancamento"] or data_ref

            # Remove vínculos anteriores desses lançamentos
            if razao_id:
                conn.execute(
                    "DELETE FROM conciliacoes WHERE razao_id=? AND cliente_id=?",
                    (razao_id, cliente_id)
                )
            if extrato_id:
                conn.execute(
                    "DELETE FROM conciliacoes WHERE extrato_id=? AND cliente_id=?",
                    (extrato_id, cliente_id)
                )
            cur = conn.execute(
                """INSERT INTO conciliacoes
                   (razao_id, extrato_id, status, tipo_match, confidence,
                    observacoes, conciliado_por, cliente_id, empresa_id)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (razao_id or None, extrato_id or None, status,
                 "MANUAL", 100.0 if dif <= 0.01 else 50.0,
                 obs, "MANUAL", cliente_id, cliente_id)
            )

        if hist_r and desc_e:
            try:
                self.registrar_padrao(
                    historico_razao=hist_r,
                    descricao_extrato=desc_e,
                    tipo_match="MANUAL",
                    confirmado_por="MANUAL",
                    data_ocorrencia=data_ref,
                )
                self.registrar_padrao_global(
                    pattern_text=hist_r,
                    match_target=desc_e,
                    pattern_type="RAZAO_EXTRATO",
                    similarity_score=1.0 if dif <= 0.01 else 0.75,
                )
            except Exception as exc:
                logger.warning(f"Falha ao registrar aprendizado manual: {exc}")
        return cur.lastrowid

    # ─────────────────────────────────────────────────────────────────────────
    # MÓDULO RAZÃO CONTÁBIL
    # ─────────────────────────────────────────────────────────────────────────

    def salvar_razao_contabil(self, cliente_id: int, df: "pd.DataFrame",
                              empresa: str = "", cnpj: str = "", periodo: str = "",
                              nome_arquivo: str = "") -> int:
        """
        Salva lançamentos do Razão Contábil na tabela razao com flag modulo='RAZAO_CONTABIL'.
        Remove dados anteriores do mesmo cliente antes de inserir.
        Retorna total de linhas inseridas.
        """
        import pandas as _pd
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM razao WHERE cliente_id=? AND modulo='RAZAO_CONTABIL'",
                (cliente_id,)
            )
            conn.execute(
                "DELETE FROM importacoes WHERE cliente_id=? AND tipo='RAZAO_CONTABIL'",
                (cliente_id,)
            )

        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO importacoes
                   (tipo, arquivo, empresa, cnpj, total_linhas, cliente_id)
                   VALUES (?,?,?,?,?,?)""",
                ("RAZAO_CONTABIL", nome_arquivo, empresa, cnpj, len(df), cliente_id)
            )
            imp_id = cur.lastrowid

        rows = []
        for _, r in df.iterrows():
            data = str(r.get("data_razao", "") or "")
            if hasattr(r.get("data_razao"), "strftime"):
                data = r["data_razao"].strftime("%Y-%m-%d")
            rows.append((
                imp_id,
                empresa, cnpj,
                str(r.get("conta_codigo", "") or ""),
                str(r.get("conta_nome", "") or ""),
                str(r.get("conta_reduzida", "") or ""),
                data,
                str(r.get("lote", "") or ""),
                str(r.get("historico", "") or ""),
                str(r.get("cta_contrapartida", "") or ""),
                float(r.get("debito", 0) or 0),
                float(r.get("credito", 0) or 0),
                float(r.get("valor_razao", 0) or 0),
                float(r.get("saldo", 0) or 0),
                float(r.get("saldo_exercicio", 0) or 0),
                (None if (r.get("saldo_anterior") is None or (isinstance(r.get("saldo_anterior"), float) and pd.isna(r.get("saldo_anterior")))) else float(r.get("saldo_anterior"))),
                cliente_id,
                "RAZAO_CONTABIL",
            ))

        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO razao
                   (importacao_id, empresa, cnpj, conta_codigo, conta_nome,
                    conta_reduzida, data_lancamento, lote, historico, cta_contrapartida,
                    debito, credito, valor, saldo, saldo_exercicio,
                    saldo_anterior, cliente_id, modulo)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows
            )
        logger.info(f"✅ Razão Contábil: {len(rows)} linhas salvas para cliente_id={cliente_id}")
        return len(rows)

    def carregar_razao_contabil(self, cliente_id: int) -> "pd.DataFrame":
        """Carrega lançamentos do Razão Contábil gravados para o cliente."""
        import pandas as _pd
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id as razao_db_id,
                          data_lancamento as data_razao, lote, historico,
                          cta_contrapartida, debito, credito, valor as valor_razao,
                          saldo, saldo_exercicio, saldo_anterior,
                          conta_codigo, conta_nome,
                          COALESCE(conta_reduzida,'') as conta_reduzida
                   FROM razao
                   WHERE cliente_id=? AND modulo='RAZAO_CONTABIL'
                   ORDER BY conta_codigo, conta_reduzida, data_lancamento""",
                (cliente_id,)
            ).fetchall()
        if not rows:
            return _pd.DataFrame()
        df = _pd.DataFrame([dict(r) for r in rows])
        df["data_razao"] = _pd.to_datetime(df["data_razao"], errors="coerce")
        return df

    def carregar_razao_ids_conciliados_bancario(self, cliente_id: int) -> set:
        """Retorna set de (data_lancamento, valor, historico) dos lançamentos do Razão
        que já foram conciliados no módulo bancário (tabela conciliacoes).
        Cruzamento por data + valor + histórico — independe de importação."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT DISTINCT
                       r.data_lancamento,
                       ROUND(r.valor, 2)  AS valor,
                       LOWER(TRIM(r.historico)) AS historico
                   FROM conciliacoes c
                   JOIN razao r ON r.id = c.razao_id
                   WHERE c.razao_id IS NOT NULL
                     AND (r.cliente_id = ? OR c.cliente_id = ?)""",
                (cliente_id, cliente_id),
            ).fetchall()
        return {
            (str(row["data_lancamento"]), float(row["valor"]), str(row["historico"] or ""))
            for row in rows
        }

    def info_razao_contabil(self, cliente_id: int) -> dict:
        """Retorna metadados da importação mais recente do Razão Contábil."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT empresa, cnpj, arquivo, total_linhas, importado_em
                   FROM importacoes
                   WHERE cliente_id=? AND tipo='RAZAO_CONTABIL'
                   ORDER BY importado_em DESC LIMIT 1""",
                (cliente_id,)
            ).fetchone()
        return dict(row) if row else {}

    def limpar_razao_contabil(self, cliente_id: int) -> int:
        """Remove todos os lançamentos do Razão Contábil do cliente. Retorna linhas removidas."""
        with self._conn() as conn:
            r = conn.execute(
                "DELETE FROM razao WHERE cliente_id=? AND modulo='RAZAO_CONTABIL'",
                (cliente_id,)
            )
            conn.execute(
                "DELETE FROM importacoes WHERE cliente_id=? AND tipo='RAZAO_CONTABIL'",
                (cliente_id,)
            )
        logger.info(f"🗑️ Razão Contábil limpo para cliente_id={cliente_id}: {r.rowcount} linhas")
        return r.rowcount

    def salvar_conciliacao_manual(
        self, cliente_id: int, conta_codigo: str, conta_reduzida: str, linhas_idx: list
    ) -> None:
        """Salva conciliações manuais do Razão Contábil no banco.
        Remove entradas anteriores da mesma conta e insere as novas.
        """
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM razao_conciliacao_manual "
                "WHERE cliente_id=? AND conta_codigo=? AND conta_reduzida=?",
                (cliente_id, conta_codigo, conta_reduzida),
            )
            conn.executemany(
                "INSERT INTO razao_conciliacao_manual "
                "(cliente_id, conta_codigo, conta_reduzida, linha_idx) VALUES (?,?,?,?)",
                [(cliente_id, conta_codigo, conta_reduzida, idx) for idx in linhas_idx],
            )
        logger.info(
            f"💾 Conciliações manuais salvas: cliente={cliente_id} "
            f"conta={conta_codigo}/{conta_reduzida} linhas={linhas_idx}"
        )

    def carregar_conciliacoes_manuais(self, cliente_id: int) -> dict:
        """Retorna dict: {manual_key → set(linha_idx)} para o cliente.
        manual_key = 'razao_manual_{conta_codigo}_{conta_reduzida}'
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT conta_codigo, conta_reduzida, linha_idx "
                "FROM razao_conciliacao_manual WHERE cliente_id=?",
                (cliente_id,),
            ).fetchall()
        result: dict = {}
        for row in rows:
            key = f"razao_manual_{row['conta_codigo']}_{row['conta_reduzida']}"
            result.setdefault(key, set()).add(row["linha_idx"])
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # AUTENTICAÇÃO E GESTÃO DE USUÁRIOS
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _hash_senha(senha: str) -> str:
        return hashlib.sha256(senha.encode("utf-8")).hexdigest()

    def autenticar(self, email: str, senha: str) -> Optional[dict]:
        """Verifica credenciais. Retorna dict do usuário ou None se inválido."""
        h = self._hash_senha(senha)
        with self._conn() as conn:
            row = conn.execute(
                """SELECT u.id, u.email, u.nome, u.perfil, u.escritorio_id,
                          e.nome AS escritorio_nome
                   FROM usuarios u
                   LEFT JOIN escritorio e ON e.id = u.escritorio_id
                   WHERE u.email=? AND u.senha_hash=? AND u.ativo=1""",
                (email.strip().lower(), h),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE usuarios SET ultimo_acesso=datetime('now','localtime') WHERE id=?",
                    (row["id"],),
                )
        return dict(row) if row else None

    def criar_usuario(self, email: str, nome: str, senha: str,
                      perfil: str, escritorio_id: int = None) -> int:
        """Cria usuário. Retorna id criado."""
        h = self._hash_senha(senha)
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO usuarios (email, nome, senha_hash, perfil, escritorio_id)
                   VALUES (?,?,?,?,?)""",
                (email.strip().lower(), nome, h, perfil, escritorio_id),
            )
        return cur.lastrowid

    def alterar_senha(self, usuario_id: int, nova_senha: str) -> None:
        h = self._hash_senha(nova_senha)
        with self._conn() as conn:
            conn.execute(
                "UPDATE usuarios SET senha_hash=? WHERE id=?", (h, usuario_id)
            )

    def listar_usuarios(self, escritorio_id: int = None) -> list:
        """Lista usuários. Se escritorio_id, filtra pelo escritório."""
        with self._conn() as conn:
            if escritorio_id:
                rows = conn.execute(
                    """SELECT u.id, u.email, u.nome, u.perfil, u.ativo,
                              e.nome AS escritorio_nome, u.escritorio_id, u.ultimo_acesso
                       FROM usuarios u LEFT JOIN escritorio e ON e.id=u.escritorio_id
                       WHERE u.escritorio_id=? ORDER BY u.nome""",
                    (escritorio_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT u.id, u.email, u.nome, u.perfil, u.ativo,
                              e.nome AS escritorio_nome, u.escritorio_id, u.ultimo_acesso
                       FROM usuarios u LEFT JOIN escritorio e ON e.id=u.escritorio_id
                       ORDER BY e.nome, u.nome"""
                ).fetchall()
        return [dict(r) for r in rows]

    def ativar_desativar_usuario(self, usuario_id: int, ativo: bool) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE usuarios SET ativo=? WHERE id=?", (1 if ativo else 0, usuario_id)
            )

    def vincular_empresas_usuario(self, usuario_id: int, cliente_ids: list) -> None:
        """Substitui vínculos de empresas do usuário."""
        with self._conn() as conn:
            conn.execute("DELETE FROM usuario_empresas WHERE usuario_id=?", (usuario_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO usuario_empresas (usuario_id, cliente_id) VALUES (?,?)",
                [(usuario_id, cid) for cid in cliente_ids],
            )

    def vincular_empresa_contabilidade(self, escritorio_id: int, cliente_ids: list) -> None:
        """Substitui vínculos empresa↔contabilidade."""
        with self._conn() as conn:
            conn.execute("DELETE FROM escritorio_clientes WHERE escritorio_id=?", (escritorio_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO escritorio_clientes (escritorio_id, cliente_id) VALUES (?,?)",
                [(escritorio_id, cid) for cid in cliente_ids],
            )

    def clientes_da_contabilidade(self, escritorio_id: int) -> list:
        """Retorna clientes vinculados a uma contabilidade."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT c.id, c.nome, c.cnpj FROM clientes c
                   JOIN escritorio_clientes ec ON ec.cliente_id = c.id
                   WHERE ec.escritorio_id=? AND c.ativo=1 ORDER BY c.nome""",
                (escritorio_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def empresas_do_usuario(self, usuario_id: int, perfil: str,
                             escritorio_id: int = None) -> list:
        """Retorna lista de clientes visíveis para o usuário.
        - igp: todos os clientes
        - gerente/usuario: apenas os vinculados à contabilidade via escritorio_clientes
        """
        with self._conn() as conn:
            if perfil == "igp":
                rows = conn.execute(
                    "SELECT id, nome, cnpj FROM clientes WHERE ativo=1 ORDER BY nome"
                ).fetchall()
            elif escritorio_id:
                # Gerente e usuário: empresas vinculadas à contabilidade
                rows = conn.execute(
                    """SELECT c.id, c.nome, c.cnpj FROM clientes c
                       JOIN escritorio_clientes ec ON ec.cliente_id = c.id
                       WHERE ec.escritorio_id=? AND c.ativo=1 ORDER BY c.nome""",
                    (escritorio_id,),
                ).fetchall()
            else:
                rows = []
        return [dict(r) for r in rows]

    def seed_usuarios_iniciais(self) -> None:
        """Cria usuários e escritórios iniciais se ainda não existirem."""
        with self._conn() as conn:
            # Garante que a tabela escritorio existe e tem os registros base
            def _escr(nome, cnpj=None):
                row = conn.execute(
                    "SELECT id FROM escritorio WHERE nome=?", (nome,)
                ).fetchone()
                if row:
                    return row["id"]
                cur = conn.execute(
                    "INSERT INTO escritorio (nome, cnpj) VALUES (?,?)", (nome, cnpj)
                )
                return cur.lastrowid

            eid_igp   = _escr("IGP")
            eid_lage  = _escr("Lage Contabilidade")
            eid_uniao = _escr("União Contabilidade Consultiva")
            eid_rnv   = _escr("R&NV")

            usuarios = [
                ("igp@igp.com.br",        "IGP Admin",   "igp@123",        "igp",     eid_igp),
                ("lage@lage.com.br",      "Lage Gerente","lage@123",       "gerente", eid_lage),
                ("ricardo@lage.com.br",   "Ricardo",     "ricardo@123",    "gerente", eid_lage),
                ("elisabete@lage.com.br", "Elisabete",   "elisabete@123",  "usuario", eid_lage),
                ("uniao@uniaoac.com.br",  "União Gerente","uniao@123",     "gerente", eid_uniao),
                ("rnv@rnv.com.br",        "R&NV Gerente","rnv@123",        "gerente", eid_rnv),
            ]
            for email, nome, senha, perfil, esc_id in usuarios:
                existe = conn.execute(
                    "SELECT id FROM usuarios WHERE email=?", (email,)
                ).fetchone()
                if not existe:
                    conn.execute(
                        """INSERT INTO usuarios (email, nome, senha_hash, perfil, escritorio_id)
                           VALUES (?,?,?,?,?)""",
                        (email, nome, self._hash_senha(senha), perfil, esc_id),
                    )
                    logger.info(f"👤 Usuário criado: {email} [{perfil}]")

    def limpar_dados_cliente(self, cliente_id: int = None) -> dict:
        """
        Remove TODOS os dados de lançamentos e conciliações de um cliente.
        Se cliente_id for None, limpa TUDO (todas as tabelas de dados).
        Preserva cadastro de clientes e escritório.
        Retorna dict com contagem de linhas removidas por tabela.
        """
        removidos = {}
        with self._conn() as conn:
            for tabela in ("conciliacoes", "razao", "extrato", "importacoes", "padroes_aprendidos"):
                if cliente_id is not None:
                    r = conn.execute(f"DELETE FROM {tabela} WHERE cliente_id=?", (cliente_id,))
                else:
                    r = conn.execute(f"DELETE FROM {tabela}")
                removidos[tabela] = r.rowcount
        logger.info(f"🗑️ Base limpa para cliente_id={cliente_id}: {removidos}")
        return removidos
