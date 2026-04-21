# =============================================================================
# MÓDULO PARSER - RAZÃO CONTÁBIL (Domínio / AFRIKA)
#
# Estrutura real do arquivo exportado pelo Domínio:
#
#   Linha 1 : Empresa: AFRIKA CONSULTORIA E TECNOLOGIA DA INFORMACAO LTDA
#   Linha 2 : C.N.P.J.: 19.925.865/0001-97
#   Linha 3 : Período: 01/01/2025 -
#   Linhas 4-6: vazias / título "RAZÃO"
#   Linha 7 : Cabeçalho — Data | Lote | Histórico | Cta.C.Part. | (esp) |
#                          Débito | Crédito | Saldo | (esp) | Saldo-Exercício
#   Linha 8 : Conta:  620  1.1.10.200.01   BANCO ITAU S/A -C/MOVIMENTO
#   Linha 9 : SALDO ANTERIOR  (ignorada)
#   Linha 10+: Lançamentos
#
# Uma nova linha "Conta:" pode aparecer ao longo do arquivo para indicar
# mudança de conta contábil.
# =============================================================================

import re
import unicodedata
import logging
import pandas as pd
from pathlib import Path
from typing import Union, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# FUNÇÕES UTILITÁRIAS
# =============================================================================

def remover_acentos(texto: str) -> str:
    if not isinstance(texto, str):
        return str(texto) if texto is not None else ""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar_texto(texto: str) -> str:
    if not isinstance(texto, str):
        return ""
    texto = remover_acentos(texto)
    texto = texto.upper()
    texto = re.sub(r"[^A-Z0-9\s/\-]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def converter_valor(valor) -> float:
    """
    Converte valor financeiro para float.
    Suporta: '1.234,56' → 1234.56 | '219,278.84' → 219278.84
    Remove sufixos 'd' (débito) e 'c' (crédito) que o Domínio adiciona ao saldo.
    """
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return 0.0
    texto = str(valor).strip()
    if texto in ("", "nan", "None"):
        return 0.0
    # Remove sufixo 'd' ou 'c' do saldo (ex: '219,278.84d' → '219,278.84')
    texto = re.sub(r'[dcDC]$', '', texto).strip()
    texto = re.sub(r"[R$\s]", "", texto)
    # Formato BR: ponto=milhar, vírgula=decimal  ex: '1.234,56'
    if "," in texto and "." in texto:
        # Verifica qual é o separador decimal (o último)
        last_comma = texto.rfind(",")
        last_dot   = texto.rfind(".")
        if last_comma > last_dot:  # vírgula é decimal (BR)
            texto = texto.replace(".", "").replace(",", ".")
        else:  # ponto é decimal (EN: '219,278.84')
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0.0


def converter_valor_com_sinal(valor) -> float:
    """
    Converte valor financeiro preservando o sinal do sufixo d/c do Domínio.
    'd' (devedor) → negativo | 'c' (credor) → positivo
    Ex: '94,38d' → -94.38 | '219.278,84c' → 219278.84
    """
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return 0.0
    texto = str(valor).strip()
    if texto in ("", "nan", "None"):
        return 0.0
    sufixo = texto[-1].lower() if texto else ""
    negativo = (sufixo == "d")
    v = converter_valor(texto)
    return -v if negativo and v != 0.0 else v


def converter_data(valor) -> pd.Timestamp:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return pd.NaT
    texto = str(valor).strip()
    if texto in ("", "nan", "None"):
        return pd.NaT
    for fmt in ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"]:
        try:
            return pd.to_datetime(texto, format=fmt)
        except Exception:
            continue
    try:
        return pd.to_datetime(texto, dayfirst=True)
    except Exception:
        return pd.NaT


# =============================================================================
# CLASSE PRINCIPAL
# =============================================================================

class RazaoParser:
    """
    Parser do Razão Contábil exportado pelo sistema Domínio.

    Colunas do arquivo real (índices base-0):
        0  = Data
        1  = Lote
        2  = Histórico
        3  = Cta.C.Part. (conta contrapartida)
        4  = (espaço / vazio)
        5  = Débito
        6  = Crédito
        7  = Saldo
        8-13 = (vazios/extras)
        15 = Saldo-Exercício

    A conta contábil vigente é identificada nas linhas onde a coluna A está
    vazia e a coluna B contém o código numérico (ex: "620") e a coluna C
    contém o código do plano (ex: "1.1.10.200.01") seguido do nome.
    """

    # Palavras que indicam linhas a ignorar
    IGNORAR = [
        "SALDO FINAL", "SALDO INICIAL",  # SALDO ANTERIOR é capturado separadamente
        "TOTAL", "SUBTOTAL", "TOTAIS", "SOMA",
        "DATA", "HISTORICO", "HISTÓRICO",   # linha de cabeçalho
        "RAZAO", "RAZÃO",
    ]

    # Índices das colunas — confirmados lendo o CSV real do Domínio
    # L06: Data|Lote|Histórico|nan|nan|nan|nan|Cta.C.Part.|Débito|Crédito|Saldo|nan|nan|Saldo-Exercício|nan
    COL_DATA     = 0
    COL_LOTE     = 1
    COL_HIST     = 2
    COL_CTA_PART = 7
    COL_DEBITO   = 8
    COL_CREDITO  = 9
    COL_SALDO    = 10
    COL_SALDO_EX = 13

    def __init__(self, conta_filtro: str = None):
        """
        Args:
            conta_filtro: Filtra apenas uma conta (busca parcial no código ou nome).
                          None = importa todas as contas do arquivo.
        """
        self.conta_filtro   = conta_filtro.upper() if conta_filtro else None
        self.conta_codigo   = ""
        self.conta_nome     = ""
        self.conta_reduzida = ""  # código interno (ex: 620)
        self.empresa        = ""
        self.cnpj           = ""
        self.periodo        = ""
        self._saldo_anterior: dict = {}  # conta_codigo -> valor do SALDO ANTERIOR

    # ─────────────────────────────────────────────────────────────────────────
    # PONTO DE ENTRADA
    # ─────────────────────────────────────────────────────────────────────────

    def carregar(self, caminho: Union[str, Path]) -> pd.DataFrame:
        """
        Carrega o arquivo do Razão e retorna DataFrame padronizado.

        Suporta: .xlsx, .xls (via openpyxl), .csv, .pdf (via pdfplumber)
        """
        caminho = Path(caminho)
        logger.info(f"📂 Carregando Razão: {caminho.name}")

        if not caminho.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")

        ext = caminho.suffix.lower()
        if ext in (".xlsx", ".xls"):
            df_bruto = self._ler_excel(caminho)
        elif ext == ".csv":
            df_bruto = self._ler_csv(caminho)
        elif ext == ".pdf":
            # PDF retorna DataFrame já final (contorna _processar_linhas)
            return self._ler_pdf_auto(caminho)
        else:
            raise ValueError(f"Formato não suportado: {ext}")

        # Extrai metadados do cabeçalho (empresa, CNPJ, período)
        self._extrair_metadados(df_bruto)

        # Processa os lançamentos linha a linha
        lancamentos = self._processar_linhas(df_bruto)

        if not lancamentos:
            logger.warning("⚠️ Nenhum lançamento encontrado.")
            return pd.DataFrame()

        df = pd.DataFrame(lancamentos)
        df = self._normalizar_dataframe(df)
        logger.info(f"✅ Razão: {len(df)} lançamentos | Empresa: {self.empresa}")
        return df

    def obter_metadados(self) -> dict:
        """Retorna metadados extraídos do cabeçalho do arquivo."""
        return {
            "empresa": self.empresa,
            "cnpj":    self.cnpj,
            "periodo": self.periodo,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # LEITURA DO ARQUIVO
    # ─────────────────────────────────────────────────────────────────────────

    def _ler_excel(self, caminho: Path) -> pd.DataFrame:
        """Lê Excel sem cabeçalho. Tenta openpyxl primeiro (xlsx), depois xlrd."""
        engines = ["openpyxl"]
        last_err = None
        for engine in engines:
            try:
                df = pd.read_excel(caminho, header=None, dtype=str, engine=engine)
                df.fillna("", inplace=True)
                return df
            except Exception as e:
                last_err = e
        raise RuntimeError(f"Não foi possível ler o Excel: {last_err}")

    def _ler_csv(self, caminho: Path) -> pd.DataFrame:
        for sep in [";", ",", "\t"]:
            for enc in ["utf-8-sig", "latin-1", "cp1252"]:
                try:
                    df = pd.read_csv(caminho, header=None, sep=sep,
                                     dtype=str, encoding=enc)
                    if df.shape[1] > 3:
                        df.fillna("", inplace=True)
                        return df
                except Exception:
                    continue
        raise ValueError("Não foi possível ler o CSV.")

    def _ler_pdf_auto(self, caminho: Path) -> pd.DataFrame:
        """
        Ponto de entrada para PDFs. Detecta o formato automaticamente:
          - Domínio formato linha única (data lote historico cta filial deb cred saldo)
          - Tenta tabelas estruturadas (formato Domínio com bordas)
          - Fallback: texto puro (formato Bellfone/TOTVS/outros)
        Retorna DataFrame já normalizado (bypass de _processar_linhas).
        """
        try:
            import pdfplumber
        except ImportError:
            raise RuntimeError("pdfplumber não instalado. Execute: pip install pdfplumber")

        # Detecta se é formato Domínio linha única
        # Indicadores: cabeçalho "LoteHistórico" OU linha "Empresa:" + "C.N.P.J.:" juntas
        with pdfplumber.open(str(caminho)) as pdf:
            txt_total = ""
            for pag in pdf.pages[:3]:
                txt_total += pag.extract_text() or ""
            _is_dominio_linha = (
                "LoteHistórico" in txt_total
                or "Lote Histórico" in txt_total
                or "Data LoteHist" in txt_total
                or "LoteHist\u00f3rico" in txt_total
                or ("Empresa:" in txt_total and "C.N.P.J.:" in txt_total
                    and "Conta:" in txt_total)
            )
            if _is_dominio_linha:
                logger.info("📄 PDF: formato Domínio linha única detectado")
                return self._ler_pdf_dominio_linha(caminho)

        # Primeiro: tenta saber se o PDF tem tabelas reais
        tem_tabelas = False
        with pdfplumber.open(str(caminho)) as pdf:
            for pag in pdf.pages[:3]:
                tbls = pag.extract_tables({"vertical_strategy": "lines_strict",
                                           "horizontal_strategy": "lines_strict"})
                if tbls and any(len(t) > 3 for t in tbls):
                    tem_tabelas = True
                    break

        if tem_tabelas:
            logger.info("📄 PDF: formato tabular detectado (Domínio)")
            return self._ler_pdf_dominios(caminho)
        else:
            logger.info("📄 PDF: formato texto detectado (Bellfone/TOTVS)")
            return self._ler_pdf_texto(caminho)

    # ─────────────────────────────────────────────────────────────────────────
    # PARSER DOMÍNIO LINHA ÚNICA
    # Formato real exportado pelo Domínio para Santander:
    #   Linha de conta: "Conta: 20 - 1.1.1.02.000013 BANCO SANTANDER..."
    #   Lançamento:     "01/12/2025 1060167 PIX RECEBIDO 318 442 141,41 141,41D"
    #   ou separado em 2 linhas por quebra do PDF (linha curta + complemento)
    # ─────────────────────────────────────────────────────────────────────────
    def _ler_pdf_dominio_linha(self, caminho: Path) -> pd.DataFrame:
        """Parser para Razão Domínio PDF com lançamentos em linha única."""
        import pdfplumber

        # Padrão: DD/MM/YYYY numero_lote HISTORICO_TEXTO num num valor[D]
        RE_LANCE   = re.compile(
            r"^(\d{2}/\d{2}/\d{4})\s+"       # data
            r"(\d+)\s+"                        # lote
            r"(.+?)\s+"                        # histórico (greedy mínimo)
            r"(\d+)\s+"                        # cta contrapartida
            r"(\d+)\s+"                        # filial
            r"([\d\.]+,\d{2})\s+"             # débito ou crédito (1º valor)
            r"([\d\.]+,\d{2}[DC]?)$"          # saldo
        )
        RE_LANCE2  = re.compile(
            r"^(\d{2}/\d{2}/\d{4})\s+"       # data
            r"(\d+)\s+"                        # lote
            r"(.+?)\s+"                        # histórico
            r"(\d+)\s+"                        # cta contrapartida
            r"(\d+)\s+"                        # filial
            r"([\d\.]+,\d{2})\s+"             # 1º valor (débito)
            r"([\d\.]+,\d{2})\s+"             # 2º valor (crédito)
            r"([\d\.]+,\d{2}[DC]?)$"          # saldo
        )
        RE_CONTA   = re.compile(
            r"Conta:\s*\d+\s*[-–]\s*([\d\.]+)\s+(.+?)(?:\s*-\s*FILIAL.*)?$",
            re.IGNORECASE
        )
        RE_CNPJ    = re.compile(r"(\d{2}[.\-]?\d{3}[.\-]?\d{3}[/\\]?\d{4}[\-]?\d{2})")
        RE_EMPRESA = re.compile(r"Empresa:\s*(.+?)(?:\s+Folha:.*)?$", re.IGNORECASE)
        IGNORAR    = {
            "SALDO ANTERIOR", "SALDO FINAL", "TOTAL DO DIA", "TOTAL",
            "DATA LOTE", "DATA LOTEHISTÓRICO", "LOTEHISTÓRICO",
        }

        lancamentos = []
        conta_codigo = ""
        conta_nome   = ""

        with pdfplumber.open(str(caminho)) as pdf:
            todas_linhas = []
            for page in pdf.pages:
                txt = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
                todas_linhas.extend(txt.splitlines())

        # Primeira passagem: metadados
        for linha in todas_linhas[:30]:
            linha = linha.strip()
            m = RE_EMPRESA.search(linha)
            if m and not self.empresa:
                self.empresa = m.group(1).strip()
                # limpa "Folha: XXXX" se estiver colado
                self.empresa = re.sub(r"\s+Folha:.*", "", self.empresa, flags=re.IGNORECASE).strip()
                # limpa fragmentos de quebra de linha: palavra isolada de 1-2 letras no final
                # ex: "ELAZA VAREJISTA LTDA Fo" → "ELAZA VAREJISTA LTDA"
                self.empresa = re.sub(r"\s+[A-Z]{1,2}$", "", self.empresa).strip()
                # limpa sufixos numéricos soltos: "LTDA 0001" → "LTDA"
                self.empresa = re.sub(r"\s+\d+\s*$", "", self.empresa).strip()
            m = RE_CNPJ.search(linha)
            if m and not self.cnpj:
                self.cnpj = m.group(1)
            if "Período:" in linha and not self.periodo:
                self.periodo = linha.strip()

        # Segunda passagem: lançamentos
        i = 0
        linhas = [l.strip() for l in todas_linhas]
        while i < len(linhas):
            linha = linhas[i]
            i += 1

            if not linha:
                continue

            linha_up = linha.upper()

            # Ignora totais e cabeçalhos
            if any(ig in linha_up for ig in IGNORAR):
                continue

            # Linha de conta contábil
            m_conta = RE_CONTA.match(linha)
            if m_conta:
                conta_codigo = m_conta.group(1).strip()
                conta_nome   = m_conta.group(2).strip()
                # Remove sufixo "- FILIAL xxx" se existir
                conta_nome = re.sub(r"\s*[-–]\s*FILIAL.*$", "", conta_nome, flags=re.IGNORECASE).strip()
                continue

            # Tenta lançamento com 3 valores (deb + cred + saldo)
            m = RE_LANCE2.match(linha)
            dois_valores = True
            if not m:
                m = RE_LANCE.match(linha)
                dois_valores = False
            if not m:
                # Linha pode estar cortada pelo PDF — tenta juntar com próxima
                if i < len(linhas) and re.match(r"^\d{2}/\d{2}/\d{4}", linha):
                    prox = linhas[i] if i < len(linhas) else ""
                    linha_junta = linha + " " + prox
                    m = RE_LANCE2.match(linha_junta)
                    dois_valores = True
                    if not m:
                        m = RE_LANCE.match(linha_junta)
                        dois_valores = False
                    if m:
                        i += 1  # consome a próxima linha
                if not m:
                    continue

            data_str   = m.group(1)
            lote       = m.group(2)
            historico  = m.group(3).strip()
            cta_part   = m.group(4)

            if dois_valores:
                val_deb_str  = m.group(6)
                val_cred_str = m.group(7)
                saldo_str    = m.group(8)
            else:
                val_deb_str  = m.group(6)
                val_cred_str = ""
                saldo_str    = m.group(7)

            debito  = converter_valor(val_deb_str)  if val_deb_str  else 0.0
            credito = converter_valor(val_cred_str) if val_cred_str else 0.0
            saldo   = converter_valor(saldo_str)

            # Determina valor líquido: se saldo termina em D → é débito
            saldo_raw = saldo_str.upper()
            if dois_valores:
                # tem débito e crédito separados
                valor = credito if credito > 0 else -debito
            else:
                # único valor: débito se saldo tem D, crédito se tem C
                if saldo_raw.endswith("D"):
                    valor = -debito
                else:
                    valor = debito

            if valor == 0.0:
                continue

            data = converter_data(data_str)
            if data is pd.NaT:
                continue

            lancamentos.append({
                "data_razao":        data,
                "lote":              lote,
                "historico":         historico,
                "cta_contrapartida": cta_part,
                "debito":            debito,
                "credito":           credito,
                "valor_razao":       abs(valor),
                "saldo":             saldo,
                "saldo_exercicio":   0.0,
                "conta_codigo":      conta_codigo,
                "conta_nome":        conta_nome,
            })

        if not lancamentos:
            logger.warning("⚠️ PDF Domínio linha: nenhum lançamento. Tentando parser de texto.")
            return self._ler_pdf_texto(caminho)

        df = pd.DataFrame(lancamentos)
        df = self._normalizar_dataframe(df)
        logger.info(f"✅ PDF Domínio linha: {len(df)} lançamentos | Empresa: {self.empresa}")
        return df

    def _ler_pdf_dominios(self, caminho: Path) -> pd.DataFrame:
        """
        Parser para PDFs com tabelas estruturadas (exportação Domínio com bordas).
        Reutiliza a estratégia de extração tabular + remapeamento de colunas.
        """
        import pdfplumber
        todas_linhas = []

        with pdfplumber.open(str(caminho)) as pdf:
            for pagina in pdf.pages:
                tabelas = pagina.extract_tables()
                for tabela in tabelas:
                    for linha in tabela:
                        if linha:
                            todas_linhas.append([str(c).strip() if c else "" for c in linha])

        if not todas_linhas:
            return pd.DataFrame()

        max_cols = max(len(l) for l in todas_linhas)
        for l in todas_linhas:
            while len(l) < max_cols:
                l.append("")

        df = pd.DataFrame(todas_linhas, dtype=str)
        df.fillna("", inplace=True)
        df = self._remapear_colunas_pdf(df)

        self._extrair_metadados(df)
        lancamentos = self._processar_linhas(df)
        if not lancamentos:
            return pd.DataFrame()
        result = pd.DataFrame(lancamentos)
        result = self._normalizar_dataframe(result)
        logger.info(f"✅ PDF Domínio: {len(result)} lançamentos")
        return result

    # ────────────────────────────────────────────────────────────────
    # PARSER TEXTO PURO — Bellfone / TOTVS / qualquer PDF sem bordas de tabela
    # Formato real da imagem:
    #   Cabeçalho página: empresa, data inicial/final, conta
    #   Linha de conta:  "1.1.1.02.000001 BANCO DO BRASIL AG 1820-1 C/C 456307-7"
    #   Lançamento:      "02/01  098.000002  REF.DOC...histórico...  250.450,42  (C)cta  saldo"
    # ────────────────────────────────────────────────────────────────

    # DD/MM ou DD/MM/AAAA no início da linha
    _RE_LANCE_DIA   = re.compile(r"^(\d{2}/\d{2}(?:/\d{4})?)\s+")
    # Lote: número com pontos e zeros (ex: 098.000002, 099.000001)
    _RE_LOTE        = re.compile(r"(\d{3}\.\d{6})")
    # Valor monetário: 1.234,56 ou 250.450,42 (com ponto de milhar obrigatório ou não)
    _RE_VALOR_MON   = re.compile(r"(?<![\w])([\d]{1,3}(?:\.\d{3})*,\d{2})(?![\d,])")
    # Conta de contrapartida: (C)1.2.3... ou (D)1.2.3...
    _RE_CTA_PART    = re.compile(r"\([CD]\)[\d\.]+")
    # Linha de conta contábil: código tipo 1.1.1.02.000001
    _RE_LINHA_CONTA = re.compile(r"^([\d\.]{5,}\d)\s+(.+)$")

    def _ler_pdf_texto(self, caminho: Path) -> pd.DataFrame:
        """
        Parser de texto puro para PDFs sem bordas de tabela (Bellfone, TOTVS, etc).
        Extrai metadados do cabeçalho e lançamentos linha a linha via regex.
        Lida com cabeçalho repetido em cada página.
        """
        import pdfplumber

        lancamentos = []
        conta_codigo = ""
        conta_nome   = ""
        data_ano     = None   # ano detectado no cabeçalho ("Data Inicial 01/01/2026")

        _RE_DATA_HEADER = re.compile(
            r"Data\s+(?:Inicial|Final|In[ií]cio)[:\s]+(\d{2}/\d{2}/(\d{4}))",
            re.IGNORECASE
        )
        _RE_EMPRESA = re.compile(r"^([A-Z][A-Z\s]{5,})$")
        _RE_CNPJ    = re.compile(r"(\d{2}[.\-]?\d{3}[.\-]?\d{3}[/\\]?\d{4}[\-]?\d{2})")

        # Palavras a ignorar (linhas de cabeçalho, totalizadores, rodapé)
        IGNORAR_LINHAS = {
            "RAZAO", "RAZÃO", "LIVRO", "FOLHA", "SALDO ANTERIOR", "SALDO FINAL",
            "SALDO INICIAL", "TOTAL", "SUBTOTAL", "CONTA", "DESCRICAO", "DESCRIÇÃO",
            "DIA", "LOTE", "DEBITO", "CREDITO", "SALDO", "DÉBITO", "CRÉDITO",
            "DOC/PARC", "N. SOLICITACAO", "DATA INICIAL", "DATA FINAL", "TIPO DE CONTA",
            "ORIGEM", "CONTRA-PARTIDA", "RELATORIO", "RELATÓRIO",
            "CTA. PARTIDA", "SALDO ANTERIOR", "DOCUMENTO HISTÓRICO",
        }

        # Regex para valores sem vírgula (formato Bellfone: 912.00, 1729.18)
        _RE_VALOR_RAW = re.compile(r"\b(\d+\.\d{2})\b")
        # Linha de descrição/histórico prévia ao lançamento
        # Ex: "REF.DOC.000000000SV N.2026000684(CREDITO CARTAO ACORDO"
        # Ex: "DOC N.384882/4 EMISSAO 28/08/2025 Cliente(TEQTEL - MC - MTZ)"
        _RE_DESC_PREVIA = re.compile(
            r"(REF\.DOC\.|DOC\s+N\.|SV\s+N\.|TRANSFERENCIA|DEBITO|CREDITO)",
            re.IGNORECASE
        )

        with pdfplumber.open(str(caminho)) as pdf:
            todas_linhas = []
            for pagina in pdf.pages:
                texto = pagina.extract_text(x_tolerance=2, y_tolerance=3) or ""
                todas_linhas.extend(texto.splitlines())

        # ── PRÉ-PROCESSAMENTO: associa histórico a cada linha de lançamento
        # Padrão Bellfone/TOTVS:
        #   Linha i-1: REF.DOC.000000000SV N.2026000684(CREDITO CARTAO ACORDO
        #   Linha i  : 02/01 098.000002 912.00 (C)2.1.6.01.000001 912,00
        #   Linha i+1: CIELO)ENTRADA 02/01/2026 ORIGEM - 1
        # Solução: montar lista de (desc_antes, linha_lancamento)

        linhas = [l.strip() for l in todas_linhas if l.strip() and len(l.strip()) >= 4]
        desc_por_idx: dict = {}   # idx_lançamento → historico

        for i, linha in enumerate(linhas):
            if not self._RE_LANCE_DIA.match(linha):
                continue
            # Linha de lançamento encontrada — busca descrição
            # Tenta linha anterior
            desc = ""
            if i > 0:
                prev = linhas[i - 1]
                if _RE_DESC_PREVIA.search(prev):
                    # Parêntese completo
                    m_h = re.search(r"\(([^)]+)\)", prev)
                    if m_h:
                        desc = m_h.group(1).strip()
                    else:
                        # Parêntese abre sem fechar → busca fechamento na linha i+1
                        m_p = re.search(r"\((.+)$", prev)
                        parcial = m_p.group(1).strip() if m_p else ""
                        if parcial and i + 1 < len(linhas):
                            prox = linhas[i + 1]
                            if ")" in prox and not self._RE_LANCE_DIA.match(prox):
                                sufixo = prox[:prox.index(")")].strip()
                                desc = (parcial + " " + sufixo).strip()
                            else:
                                desc = parcial
                        else:
                            # Sem parêntese: remove prefixo técnico
                            desc = re.sub(
                                r"^(REF\.DOC\.\S*\s*|DOC\s+N\.\S+\s+EMISSAO\s+\S+\s+)",
                                "", prev, flags=re.IGNORECASE
                            ).strip()
                            desc = re.sub(r"^Cliente\(", "", desc, flags=re.IGNORECASE).strip()
            # Limpa barra/parêntese solto no final
            desc = re.sub(r"[\(\)/]+$", "", desc).strip()
            desc_por_idx[i] = desc

        # ── PROCESSAMENTO PRINCIPAL
        num_pag = 0
        for i, linha in enumerate(linhas):
            linha_up = linha.upper()

            # Cabeçalho empresa — ignora palavras-chave do relatório
            _NAO_EMPRESA = {
                "CONSOLIDADO", "RAZÃO", "RAZAO", "EXTRATO", "PERIÓDO",
                "PERIODO", "RELATÓRIO", "RELATORIO", "BALANCETE",
                "DETALHE", "FOLHA", "PÁGINA", "PAGINA",
            }
            if (not self.empresa and _RE_EMPRESA.match(linha)
                    and not any(c.isdigit() for c in linha)
                    and linha.strip().upper() not in _NAO_EMPRESA):
                self.empresa = linha.strip()
                continue

            # CNPJ
            if not self.cnpj:
                m = _RE_CNPJ.search(linha)
                if m:
                    self.cnpj = m.group(1)

            # Período
            m = _RE_DATA_HEADER.search(linha)
            if m:
                self.periodo = linha.strip()
                data_ano = m.group(2)
                continue

            # Ignora cabeçalhos
            if any(ig in linha_up for ig in IGNORAR_LINHAS):
                continue

            # Conta contábil
            m = self._RE_LINHA_CONTA.match(linha)
            if m and '.' in m.group(1) and not self._RE_LANCE_DIA.match(linha):
                conta_codigo = m.group(1).strip()
                conta_nome   = m.group(2).strip()
                conta_nome   = re.sub(r"\s+Saldo\s+Anterior.*$", "", conta_nome, flags=re.IGNORECASE).strip()
                continue

            # Lançamento
            m_dia = self._RE_LANCE_DIA.match(linha)
            if not m_dia:
                continue

            data_str = m_dia.group(1)
            resto    = linha[m_dia.end():].strip()

            if len(data_str) == 5 and data_ano:
                data_str = f"{data_str}/{data_ano}"

            data = converter_data(data_str)
            if data is pd.NaT:
                continue

            m_lote = self._RE_LOTE.search(resto)
            lote   = m_lote.group(1) if m_lote else ""

            m_cta   = self._RE_CTA_PART.search(resto)
            cta_part = m_cta.group(0) if m_cta else ""

            # Valores BR (1.234,56) depois valores raw (912.00)
            valores = self._RE_VALOR_MON.findall(resto)
            if not valores:
                valores = [v for v in _RE_VALOR_RAW.findall(resto)
                           if not re.match(r"^\d{3}\.\d{6}$", v)]
            if not valores:
                continue

            debito = credito = saldo = 0.0
            if len(valores) >= 2:
                saldo         = converter_valor(valores[-1])
                val_principal = converter_valor(valores[-2])
            else:
                val_principal = converter_valor(valores[0])

            if "(D)" in cta_part.upper():
                credito = val_principal
                valor   = -credito
            else:
                debito = val_principal
                valor  = debito

            if valor == 0.0:
                continue

            # Histórico do pré-processamento, fallback conta_nome / lote
            historico = desc_por_idx.get(i, "") or conta_nome or lote

            lancamentos.append({
                "data_razao":        data,
                "lote":              lote,
                "historico":         historico,
                "cta_contrapartida": cta_part,
                "debito":            debito,
                "credito":           credito,
                "valor_razao":       valor,
                "saldo":             saldo,
                "saldo_exercicio":   0.0,
                "conta_codigo":      conta_codigo,
                "conta_nome":        conta_nome,
            })

        if not lancamentos:
            logger.warning("⚠️ PDF texto: nenhum lançamento extraído.")
            return pd.DataFrame()

        df = pd.DataFrame(lancamentos)
        df = self._normalizar_dataframe(df)
        logger.info(f"✅ PDF texto: {len(df)} lançamentos | Empresa: {self.empresa}")
        return df

    # ── helpers do PDF ───────────────────────────────────────────────────────

    _RE_DATA  = re.compile(r"^\d{2}/\d{2}/\d{4}$")
    _RE_VALOR = re.compile(r"^-?[\d.,]+[dDcC]?$")
    _RE_CONTA = re.compile(r"\d+\.\d+\.\d+")
    _RE_CNPJ  = re.compile(r"\d{2}[.\-]?\d{3}[.\-]?\d{3}[/\\]?\d{4}[\-]?\d{2}")

    def _tokenizar_linha_pdf(self, linha: str) -> list:
        """
        Divide uma linha de texto do PDF em tokens para montagem do DataFrame.
        O Domínio exporta as colunas separadas por 2+ espaços.
        """
        # Separa por 2+ espaços consecutivos
        partes = re.split(r"  +", linha.strip())
        return [p.strip() for p in partes if p.strip()]

    def _remapear_colunas_pdf(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        O PDF pode ter menos colunas que o Excel (sem colunas vazias intermediárias).
        Detecta automaticamente qual coluna é Data, Histórico, Débito, Crédito, Saldo
        e reorganiza para os índices esperados pelo _processar_linhas.

        Layout alvo (COL_* da classe):
          0=Data  1=Lote  2=Hist  7=CtaPart  8=Deb  9=Cred  10=Saldo  13=SaldoEx
        """
        ncols = df.shape[1]

        # Detecta automaticamente colunas por conteúdo
        idx_data   = self._detectar_col(df, lambda v: bool(self._RE_DATA.match(v)))
        idx_hist   = self._detectar_col_texto(df, skip_cols={idx_data})
        idx_debito, idx_credito, idx_saldo = self._detectar_cols_valor(df, skip_data=idx_data)

        # Se já tem colunas suficientes e parece layout correto → devolve sem remap
        if ncols >= 11 and idx_data in (0, None):
            return df

        # Reconstrói DataFrame no layout padrão de 14 colunas
        n = len(df)
        novo = pd.DataFrame("", index=range(n), columns=range(14))

        def copiar(src_idx, dst_idx):
            if src_idx is not None and src_idx < ncols:
                novo[dst_idx] = df.iloc[:, src_idx].values

        copiar(idx_data,    self.COL_DATA)      # 0
        # Lote: coluna logo após data
        lote_idx = (idx_data + 1) if idx_data is not None and (idx_data + 1) != idx_hist else None
        copiar(lote_idx,    self.COL_LOTE)      # 1
        copiar(idx_hist,    self.COL_HIST)      # 2
        copiar(idx_debito,  self.COL_DEBITO)    # 8
        copiar(idx_credito, self.COL_CREDITO)   # 9
        copiar(idx_saldo,   self.COL_SALDO)     # 10

        # Conta contrapartida: coluna entre hist e débito
        if idx_hist is not None and idx_debito is not None and idx_debito - idx_hist > 1:
            copiar(idx_hist + 1, self.COL_CTA_PART)  # 7

        # Saldo exercício: última coluna de valor
        if idx_saldo is not None and idx_saldo + 1 < ncols:
            copiar(idx_saldo + 1, self.COL_SALDO_EX)  # 13

        # Preserva linhas de cabeçalho (empresa/CNPJ) nas primeiras linhas
        # copiando a linha inteira como texto concatenado na col 0
        for ridx in range(min(5, n)):
            linha_raw = " ".join(df.iloc[ridx].tolist()).strip()
            if any(k in linha_raw.upper() for k in ("EMPRESA", "CNPJ", "PERIODO", "RAZAO", "PERÍODO")):
                novo.iloc[ridx, 0] = linha_raw
                for c in range(1, 14):
                    novo.iloc[ridx, c] = ""

        novo.fillna("", inplace=True)
        return novo

    def _detectar_col(self, df: pd.DataFrame, predicado) -> Optional[int]:
        """Retorna índice da primeira coluna onde >= 30% das células satisfazem o predicado."""
        for idx in range(df.shape[1]):
            vals = df.iloc[:, idx].tolist()
            hits = sum(1 for v in vals if predicado(str(v).strip()))
            if hits / max(len(vals), 1) >= 0.30:
                return idx
        return None

    def _detectar_col_texto(self, df: pd.DataFrame, skip_cols: set) -> Optional[int]:
        """Detecta a coluna de histórico (maior densidade de texto alfabético longo)."""
        melhor_idx  = None
        melhor_score = 0
        for idx in range(df.shape[1]):
            if idx in skip_cols or idx in (skip_cols or set()):
                continue
            vals = df.iloc[:, idx].tolist()
            score = sum(
                len(v) for v in vals
                if len(str(v)) > 4 and re.search(r"[A-Za-záàãâéêíóôõúç]", str(v))
            )
            if score > melhor_score:
                melhor_score = score
                melhor_idx   = idx
        return melhor_idx

    def _detectar_cols_valor(self, df: pd.DataFrame, skip_data=None):
        """Detecta as colunas de débito, crédito e saldo (últimas colunas numéricas)."""
        cols_valor = []
        for idx in range(df.shape[1]):
            if idx == skip_data:
                continue
            vals = df.iloc[:, idx].tolist()
            hits = sum(1 for v in vals if self._RE_VALOR.match(str(v).strip()) and str(v).strip())
            if hits / max(len(vals), 1) >= 0.15:
                cols_valor.append(idx)
        # Pega as últimas 3-4 colunas numéricas como deb/cred/saldo/saldo_ex
        debito  = cols_valor[-4] if len(cols_valor) >= 4 else (cols_valor[-3] if len(cols_valor) >= 3 else None)
        credito = cols_valor[-3] if len(cols_valor) >= 3 else (cols_valor[-2] if len(cols_valor) >= 2 else None)
        saldo   = cols_valor[-2] if len(cols_valor) >= 2 else (cols_valor[-1] if cols_valor else None)
        return debito, credito, saldo

    # ─────────────────────────────────────────────────────────────────────────
    # EXTRAÇÃO DE METADADOS DO CABEÇALHO
    # ─────────────────────────────────────────────────────────────────────────

    def _extrair_metadados(self, df: pd.DataFrame):
        """
        Lê as primeiras linhas para capturar empresa, CNPJ e período.
        Linha 0 → Empresa | Linha 1 → CNPJ | Linha 2 → Período
        """
        def _cel(row_idx, col_idx):
            try:
                return str(df.iloc[row_idx, col_idx]).strip()
            except Exception:
                return ""

        # Linha 0: "Empresa:" na col 0, nome na col 1 ou 2
        linha0 = " ".join(str(v) for v in df.iloc[0].tolist() if str(v).strip())
        match = re.search(r"Empresa\s*[:\-]?\s*(.+)", linha0, re.IGNORECASE)
        if match:
            self.empresa = match.group(1).strip()
        else:
            # Tenta col 1 diretamente
            self.empresa = _cel(0, 1) or _cel(0, 2)
        self.empresa = re.sub(r"\bCONSOLIDADO\b", "", self.empresa or "", flags=re.IGNORECASE).strip(" -\n\r\t")

        # Linha 1: CNPJ
        linha1 = " ".join(str(v) for v in df.iloc[1].tolist() if str(v).strip())
        match = re.search(r"(\d{2}[\.\-]?\d{3}[\.\-]?\d{3}[/\\]?\d{4}[\-]?\d{2})", linha1)
        if match:
            self.cnpj = match.group(1)

        # Linha 2: Período
        linha2 = " ".join(str(v) for v in df.iloc[2].tolist() if str(v).strip())
        match = re.search(r"Per[íi]odo\s*[:\-]?\s*(.+)", linha2, re.IGNORECASE)
        if match:
            self.periodo = match.group(1).strip()
        self.periodo = re.sub(r"\bCONSOLIDADO\b", "", self.periodo or "", flags=re.IGNORECASE).strip(" -\n\r\t")

    # ─────────────────────────────────────────────────────────────────────────
    # PROCESSAMENTO LINHA A LINHA
    # ─────────────────────────────────────────────────────────────────────────

    def _processar_linhas(self, df: pd.DataFrame) -> list:
        lancamentos = []
        ncols = df.shape[1]

        def cel(row, idx):
            return str(row.iloc[idx]).strip() if idx < ncols else ""

        for ridx, row in df.iterrows():
            col_a = cel(row, self.COL_DATA)
            col_b = cel(row, self.COL_LOTE)
            col_c = cel(row, self.COL_HIST)

            linha_str = " ".join(str(v) for v in row.tolist()).upper()

            # ── Detecta linha de identificação de conta ───────────────────────
            if self._e_linha_conta(col_a, col_b, col_c):
                cod, nom, red = self._extrair_conta(row, ncols)
                self.conta_codigo   = re.sub(r"\s+", " ", cod).strip()
                self.conta_nome     = re.sub(r"\s+", " ", nom).strip()
                self.conta_reduzida = re.sub(r"\s+", " ", red).strip()
                logger.debug(f"🏦 Conta: {self.conta_codigo} — {self.conta_nome}")
                continue

            # ── Captura SALDO ANTERIOR (col C contém "SALDO ANTERIOR", valor na col N=13) ──
            if "SALDO ANTERIOR" in linha_str.upper():
                sa_val = converter_valor_com_sinal(cel(row, self.COL_SALDO_EX))
                if sa_val == 0.0:
                    sa_val = converter_valor_com_sinal(cel(row, self.COL_SALDO))
                if self.conta_codigo:
                    self._saldo_anterior[self.conta_codigo] = sa_val
                continue

            # ── Ignora linhas de totalizador / cabeçalho / vazias ─────────────────────────
            if self._e_ignorar(linha_str, col_a):
                continue

            # ── Tenta extrair lançamento ──────────────────────────────────────
            data = converter_data(col_a)
            if data is pd.NaT:
                continue

            lote        = col_b
            historico   = cel(row, self.COL_HIST)
            cta_part    = cel(row, self.COL_CTA_PART)
            debito      = converter_valor(cel(row, self.COL_DEBITO))
            credito     = converter_valor(cel(row, self.COL_CREDITO))
            saldo       = converter_valor_com_sinal(cel(row, self.COL_SALDO))
            saldo_ex    = converter_valor_com_sinal(cel(row, self.COL_SALDO_EX)) if ncols > self.COL_SALDO_EX else 0.0

            # Valor líquido: positivo = débito, negativo = crédito
            if debito != 0.0:
                valor = debito
            elif credito != 0.0:
                valor = -credito
            else:
                continue  # linha sem valor financeiro

            # Aplica filtro de conta
            if self.conta_filtro:
                chave = f"{self.conta_codigo} {self.conta_nome}".upper()
                if self.conta_filtro not in chave:
                    continue

            chave_sa = re.sub(r"\s+", " ", self.conta_codigo).strip()
            lancamentos.append({
                "data_razao":        data,
                "lote":              lote,
                "historico":         historico,
                "cta_contrapartida": cta_part,
                "debito":            debito,
                "credito":           credito,
                "valor_razao":       valor,
                "saldo":             saldo,
                "saldo_exercicio":   saldo_ex,
                "saldo_anterior":    self._saldo_anterior.get(chave_sa),  # None = linha SA não encontrada
                "conta_codigo":      self.conta_codigo,
                "conta_nome":        self.conta_nome,
                "conta_reduzida":    self.conta_reduzida,
            })

        return lancamentos

    def _e_linha_conta(self, col_a: str, col_b: str, col_c: str) -> bool:
        """
        Detecta linha de identificação de conta contábil.
        Padrão Domínio no CSV real:
          col A = 'Conta:'  col B = código numérico (ex: '620')
          col C = código contábil (ex: '1.1.10.200.01')
        """
        if col_a.strip().lower().startswith("conta"):
            return True
        # Fallback: col A vazia e col C tem código de plano de contas
        if not col_a and re.search(r"\d+\.\d+\.\d+", col_c):
            return True
        return False

    def _extrair_conta(self, row, ncols: int) -> tuple:
        """
        Extrai (codigo, nome, reduzida) da linha de conta.
        No CSV real: col1=código reduzido (620), col2=código (1.1.10.200.01), col5=nome
        Retorna tupla (codigo_contabil, nome, codigo_reduzido)
        """
        def cel(idx):
            if idx >= ncols:
                return ""
            return re.sub(r"\s+", " ", str(row.iloc[idx])).strip()

        # col_b (COL_LOTE = 1) pode conter o código reduzido numérico (ex: 620)
        reduzida = ""
        col_b_val = cel(self.COL_LOTE)
        if re.match(r"^\d+$", col_b_val):
            reduzida = col_b_val

        # Procura código contábil em colunas 2..7
        codigo = ""
        nome = ""
        for idx in range(2, min(8, ncols)):
            v = cel(idx)
            if re.search(r"\d+\.\d+\.\d+", v):
                codigo = v.strip()
                for nidx in range(idx + 1, min(ncols, idx + 5)):
                    nv = cel(nidx)
                    if nv and nv.lower() not in ("nan", ""):
                        nome = nv.strip()
                        break
                break
        if not codigo:
            codigo = cel(self.COL_LOTE)
        return codigo, nome, reduzida

    def _e_ignorar(self, linha_str: str, col_a: str) -> bool:
        """Retorna True para linhas que devem ser puladas."""
        if not linha_str.strip():
            return True
        return any(palavra in linha_str for palavra in self.IGNORAR)

    # ─────────────────────────────────────────────────────────────────────────
    # NORMALIZAÇÃO FINAL
    # ─────────────────────────────────────────────────────────────────────────

    def _normalizar_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        df["historico_norm"] = df["historico"].apply(normalizar_texto)
        df["conta_norm"]     = df["conta_nome"].apply(normalizar_texto)

        df["data_razao"] = pd.to_datetime(df["data_razao"], errors="coerce")

        for col in ["debito", "credito", "valor_razao", "saldo", "saldo_exercicio"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        if "saldo_anterior" in df.columns:
            df["saldo_anterior"] = pd.to_numeric(df["saldo_anterior"], errors="coerce")  # None → NaN, preserva sentinela

        df["used"] = False
        df.reset_index(drop=True, inplace=True)
        return df


# =============================================================================
# EXECUÇÃO DIRETA — teste isolado
# =============================================================================
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s — %(message)s")

    caminho = sys.argv[1] if len(sys.argv) > 1 else \
              "/Users/eduardomassarente/Projeto_Lage/RAZAO 202501 -202601 - AFRIKA 3(Razão).csv"

    parser = RazaoParser(conta_filtro=None)
    df = parser.carregar(caminho)

    meta = parser.obter_metadados()
    print(f"\nEmpresa : {meta['empresa']}")
    print(f"CNPJ    : {meta['cnpj']}")
    print(f"Período : {meta['periodo']}")
    print(f"\n📊 {len(df)} lançamentos encontrados\n")
    print(df[["data_razao","conta_codigo","lote","historico",
              "debito","credito","valor_razao","saldo"]].to_string())
