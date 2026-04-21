# =============================================================================
# MÓDULO PARSER - EXTRATO BANCÁRIO
# Responsável por ler o extrato bancário (Excel ou CSV) e transformar
# em um DataFrame padronizado para a engine de conciliação.
#
# Suporta múltiplos formatos de extrato:
# - Extrato genérico (data, descrição, valor, tipo)
# - Formato OFX/CSV de bancos brasileiros (BB, Itaú, Bradesco, Santander, CEF)
# =============================================================================

import re
import unicodedata
import logging
import pandas as pd
from pathlib import Path
from typing import Union

# Importa as funções de normalização do parser do Razão para reutilizar
# Suporta execução como pacote (from import_.razao_parser) e como script direto
try:
    from import_.razao_parser import (
        remover_acentos,
        normalizar_texto,
        converter_valor,
        converter_data,
    )
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from import_.razao_parser import (
        remover_acentos,
        normalizar_texto,
        converter_valor,
        converter_data,
    )

logger = logging.getLogger(__name__)


# =============================================================================
# CLASSE PRINCIPAL - EXTRATO PARSER
# =============================================================================

class ExtratoParser:
    """
    Lê e processa o extrato bancário exportado pelo banco.

    Suporte principal: formato real Itaú Excel (6 colunas):
        Data | Lançamento | Razão Social | CPF/CNPJ | Valor (R$) | Saldo (R$)

    Metadados extraídos do cabeçalho:
        Nome, Agência, Conta, Período

    Também funciona com CSVs genéricos de outros bancos via auto-detecção.
    """

    # Mapeamento de nomes alternativos para cada coluna esperada
    # O parser tenta encontrar esses nomes no cabeçalho do arquivo
    MAPA_COLUNAS = {
        "data": ["data", "dt", "date", "data lancamento", "data lançamento",
                 "data mov", "data movimento", "data transacao", "data transação"],
        "descricao": ["descricao", "descrição", "historico", "histórico",
                      "memo", "description", "complemento", "lancamento",
                      "lançamento", "detalhe", "narrativa"],
        "valor": ["valor", "value", "amount", "vlr", "vl", "montante"],
        "tipo": ["tipo", "type", "natureza", "dc", "d/c", "debito credito",
                 "debcred", "sinal"],
        "documento": ["documento", "doc", "docto", "nr doc", "numero doc",
                      "numero documento", "referencia", "referência",
                      "id transacao", "id transação", "txid", "autenticacao"],
    }

    # Linhas do extrato a ignorar (totalizadores/saldos sem valor de lançamento)
    IGNORAR_DESCRICAO = [
        "SALDO TOTAL DISPONÍVEL DIA",
        "SALDO ANTERIOR",
        "SALDO FINAL",
        "SALDO INICIAL",
        "TOTAL DO DIA",
    ]

    def __init__(self):
        self._mapa_indices = {}  # Guarda qual coluna do arquivo mapeia para qual campo
        self.nome_conta   = ""
        self.agencia      = ""
        self.conta        = ""
        self.periodo      = ""
        self.banco        = ""

    def carregar(self, caminho: Union[str, Path], nome_original: str = "") -> pd.DataFrame:
        """
        Carrega e processa o arquivo de extrato bancário.

        Args:
            caminho: Caminho do arquivo (pode ser arquivo temporário)
            nome_original: Nome original do arquivo (usado para detecção do banco
                           quando caminho é um arquivo temporário sem nome descritivo)

        Returns:
            DataFrame com colunas padronizadas, pronto para conciliação
        """
        caminho = Path(caminho)
        self._nome_original = nome_original.upper() if nome_original else caminho.stem.upper()
        logger.info(f"📂 Carregando extrato: {nome_original or caminho.name}")

        if not caminho.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")

        ext = caminho.suffix.lower()
        if ext in (".xlsx", ".xls"):
            df_bruto = self._ler_excel(caminho)
            # _ler_html_xls retorna DataFrame já processado (colunas finais)
            if "data_extrato" in df_bruto.columns:
                logger.info(f"✅ Extrato: {len(df_bruto)} lançamentos | Conta: {self.conta}")
                return df_bruto
            df = self._mapear_colunas(df_bruto)
            df = self._filtrar_linhas_validas(df)
            df = self._normalizar_dataframe(df)
        elif ext == ".csv":
            df_bruto = self._ler_csv(caminho)
            df = self._mapear_colunas(df_bruto)
            df = self._filtrar_linhas_validas(df)
            df = self._normalizar_dataframe(df)
        elif ext == ".pdf":
            df = self._ler_pdf_auto(caminho)
        else:
            raise ValueError(f"Formato não suportado: {ext}")

        logger.info(f"✅ Extrato: {len(df)} lançamentos | Conta: {self.conta}")
        return df

    def obter_metadados(self) -> dict:
        """Retorna metadados extraídos do cabeçalho do extrato."""
        return {
            "nome":    self.nome_conta,
            "agencia": self.agencia,
            "conta":   self.conta,
            "periodo": self.periodo,
        }

    # -------------------------------------------------------------------------
    # LEITURA DO ARQUIVO
    # -------------------------------------------------------------------------
    def _ler_excel(self, caminho: Path) -> pd.DataFrame:
        """Lê arquivo Excel, extrai metadados do cabeçalho e retorna a tabela."""
        # .xls (BIFF/Excel 97-2003) exige xlrd; .xlsx usa openpyxl
        engine = "xlrd" if str(caminho).lower().endswith(".xls") else "openpyxl"
        try:
            df_raw = pd.read_excel(caminho, header=None, dtype=str, engine=engine)
        except Exception as e_xls:
            # Muitos bancos exportam HTML com extensão .xls
            logger.warning(f"⚠️ xlrd falhou ({e_xls}), tentando HTML-XLS...")
            return self._ler_html_xls(caminho)

        df_raw.fillna("", inplace=True)

        # Extrai metadados das primeiras linhas (formato Itaú)
        self._extrair_metadados_excel(df_raw)

        linha_header = self._encontrar_linha_cabecalho(df_raw)
        logger.debug(f"📋 Cabeçalho detectado na linha: {linha_header}")

        df = pd.read_excel(caminho, header=linha_header, dtype=str, engine=engine)
        df.fillna("", inplace=True)
        return df

    # -------------------------------------------------------------------------
    # DISPATCHER: detecta banco pelo nome do arquivo e chama o parser certo
    # -------------------------------------------------------------------------
    def _ler_pdf_auto(self, caminho: Path) -> pd.DataFrame:
        """Detecta o banco pelo nome do arquivo e chama o parser correto."""
        nome = getattr(self, "_nome_original", caminho.stem.upper())
        if "CEF" in nome or "CAIXA" in nome:
            self.banco = "CEF"
            return self._ler_pdf_cef(caminho)
        if "NEXOOS" in nome:
            self.banco = "NEXOOS"
            return self._ler_pdf_nexoos(caminho)
        if "XP" in nome or "XP INVESTIMENTOS" in nome:
            self.banco = "XP Investimentos"
            return self._ler_pdf_xp(caminho)
        if "SANTANDER" in nome:
            self.banco = "Santander"
            return self._ler_pdf_santander(caminho)
        # Detecção pelo conteúdo do PDF (fallback quando nome não identifica o banco)
        try:
            import pdfplumber as _pp
            with _pp.open(str(caminho)) as _pdf:
                _txt = (_pdf.pages[0].extract_text() or "") + (_pdf.pages[1].extract_text() if len(_pdf.pages) > 1 else "")
            if "EXTRATO CONSOLIDADO" in _txt.upper() and ("SANTANDER" in _txt.upper() or "0389" in _txt):
                self.banco = "Santander"
                return self._ler_pdf_santander(caminho)
        except Exception:
            pass
        if "BANCO DO BRASIL" in nome or "BB " in nome or nome.startswith("BB") or "BRASIL" in nome:
            self.banco = "Banco do Brasil"
            return self._ler_pdf_bb(caminho)
        if "BRADESCO" in nome:
            self.banco = "Bradesco"
            return self._ler_pdf_bradesco(caminho)
        if "DAYCOVAL" in nome:
            raise ValueError(
                "PDF do Daycoval é gerado por imagem escaneada e não pode ser "
                "lido automaticamente. Solicite o extrato em formato OFX/CSV pelo "
                "internet banking do Daycoval."
            )
        # Default: tenta parser do Itaú
        self.banco = "Itaú"
        return self._ler_pdf_itau(caminho)

    # -------------------------------------------------------------------------
    # PARSER CEF — tabela 6 colunas
    # Colunas: Data lançamento | Data movimento | Documento | Histórico | Valor(R$) | Saldo(R$)
    # -------------------------------------------------------------------------
    def _ler_pdf_cef(self, caminho: Path) -> pd.DataFrame:
        """Lê extrato PDF da Caixa Econômica Federal."""
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("pip install pdfplumber")

        # Prefixos de histórico que indicam Débito na CEF (sem sinal no valor)
        PREFIXOS_DEBITO = {
            "DEB", "DB ", "PREST", "SEGUR", "BOLETO", "IOF", "TARIFA",
            "TAR ", "SAQ", "TRANSF", "ENVIO", "PGTO", "PAGTO",
        }
        PREFIXOS_CREDITO = {
            "CRED", "DEP", "RESG", "TED", "PIX CRED", "CRED PIX",
            "CRED AUT", "FOL",
        }
        IGNORAR_HIST = {"SALDO DIA", "SALDO ANTERIOR", "SALDO FINAL",
                        "SALDO INICIAL", "TOTAL"}

        lancamentos = []

        with pdfplumber.open(caminho) as pdf:
            texto_p1 = pdf.pages[0].extract_text() or ""
            m = re.search(r"Conta[:\s]*([\d\.\-]+)", texto_p1, re.IGNORECASE)
            if m:
                self.conta = m.group(1)
            m = re.search(r"Ag[eê]ncia[:\s]*([\d\.\-]+)", texto_p1, re.IGNORECASE)
            if m:
                self.agencia = m.group(1)

            for page in pdf.pages:
                for tabela in page.extract_tables():
                    for row in tabela:
                        if not row or len(row) < 5:
                            continue
                        data_raw  = str(row[0] or "").strip()
                        doc_raw   = str(row[2] or "").strip()
                        desc_raw  = str(row[3] or "").strip()
                        valor_raw = str(row[4] or "").strip()

                        if not data_raw or not desc_raw:
                            continue
                        if "data" in data_raw.lower():
                            continue

                        desc_up = desc_raw.upper().strip()
                        if any(ig in desc_up for ig in IGNORAR_HIST):
                            continue

                        data = converter_data(data_raw)
                        if data is None:
                            continue

                        valor_raw = valor_raw.replace("R$", "").strip()
                        valor = converter_valor(valor_raw)
                        if valor == 0.0:
                            continue

                        # Detecta tipo pelo prefixo do histórico
                        if any(desc_up.startswith(p) for p in PREFIXOS_DEBITO):
                            tipo = "D"
                        elif any(desc_up.startswith(p) for p in PREFIXOS_CREDITO):
                            tipo = "C"
                        else:
                            tipo = "C"  # default conservador

                        lancamentos.append({
                            "data_extrato":   pd.Timestamp(data),
                            "descricao":      desc_raw,
                            "descricao_norm": normalizar_texto(desc_raw),
                            "valor_extrato":  abs(valor),
                            "tipo":           tipo,
                            "documento":      doc_raw,
                            "documento_norm": normalizar_texto(doc_raw),
                            "used":           False,
                        })

        return self._montar_df(lancamentos)

    # -------------------------------------------------------------------------
    # PARSER NEXOOS — texto bruto com letras duplicadas (fonte dupla no PDF)
    # Cada linha: DD/MM/AAAA DESCRICAO VALOR_CRED VALOR_DEB SALDO
    # -------------------------------------------------------------------------
    def _ler_pdf_nexoos(self, caminho: Path) -> pd.DataFrame:
        """Lê extrato PDF do Nexoos (fintech). Fonte duplicada — dedup de chars."""
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("pip install pdfplumber")

        def dedup(texto: str) -> str:
            """Remove duplicação de caracteres: 'DDAATTAA' → 'DATA'."""
            if not texto:
                return texto
            out = [texto[0]]
            for i in range(1, len(texto)):
                if texto[i] != texto[i - 1]:
                    out.append(texto[i])
            return "".join(out)

        lancamentos = []
        IGNORAR = {"SALDO", "TOTAL", "TARIFAS", "EMITIDO", "DATA DA EMISSAO"}
        DATA_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(.+)")

        with pdfplumber.open(caminho) as pdf:
            # Metadados da 1ª linha útil
            texto_p1 = dedup(pdf.pages[0].extract_text() or "")
            m = re.search(r"Conta\s*([\d\.\-]+)", texto_p1, re.IGNORECASE)
            if m:
                self.conta = m.group(1)
            m = re.search(r"Periodo[:\s]*([\d/]+\s*-\s*[\d/]+)", texto_p1, re.IGNORECASE)
            if m:
                self.periodo = m.group(1)

            for page in pdf.pages:
                texto_raw = page.extract_text() or ""
                texto = dedup(texto_raw)

                for linha in texto.split("\n"):
                    linha = linha.strip()
                    m = DATA_RE.match(linha)
                    if not m:
                        continue

                    data_str = m.group(1)
                    resto    = m.group(2).strip()

                    data = converter_data(data_str)
                    if data is None:
                        continue

                    # Ignora linhas de saldo / cabeçalho
                    resto_up = resto.upper()
                    if any(ig in resto_up for ig in IGNORAR):
                        continue

                    # Extrai todos os números da linha
                    nums = re.findall(r"[\d\.]+,\d{2}", resto)
                    if not nums:
                        continue

                    # Remove os números do texto para ficar só a descrição
                    desc = re.sub(r"[\d\.]+,\d{2}", "", resto).strip()
                    desc = re.sub(r"\s{2,}", " ", desc).strip()

                    # Nexoos: Crédito vem antes de Débito na linha
                    # Se há 2+ números: 1º = crédito ou débito, 2º = saldo
                    # Detecta pelo contexto: RECEBIMENTO=crédito, ENVIO=débito
                    valor_str = nums[0]
                    valor = converter_valor(valor_str)
                    if valor == 0.0:
                        continue

                    desc_up = desc.upper()
                    if "ENVIO" in desc_up or "PAGAMENTO" in desc_up or "DEBITO" in desc_up:
                        tipo = "D"
                    else:
                        tipo = "C"

                    lancamentos.append({
                        "data_extrato":   pd.Timestamp(data),
                        "descricao":      desc,
                        "descricao_norm": normalizar_texto(desc),
                        "valor_extrato":  abs(valor),
                        "tipo":           tipo,
                        "documento":      "",
                        "documento_norm": "",
                        "used":           False,
                    })

        return self._montar_df(lancamentos)

    # -------------------------------------------------------------------------
    # PARSER XP INVESTIMENTOS — tabela [Liq, Mov, Histórico, '', Valor, Saldo]
    # -------------------------------------------------------------------------
    def _ler_pdf_xp(self, caminho: Path) -> pd.DataFrame:
        """Lê extrato PDF da XP Investimentos."""
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("pip install pdfplumber")

        lancamentos = []
        IGNORAR = {"SALDO", "LANCAMENTOS FUTUROS", "LANÇAMENTOS FUTUROS",
                   "LIQ", "MOV", "HISTORICO", "HISTÓRICO",
                   "NAO HA LANCAMENTOS", "NÃO HÁ LANÇAMENTOS"}

        with pdfplumber.open(caminho) as pdf:
            texto_p1 = pdf.pages[0].extract_text() or ""
            m = re.search(r"Conta[:\s]*([\d\.\-/]+)", texto_p1, re.IGNORECASE)
            if m:
                self.conta = m.group(1)

            for page in pdf.pages:
                for tabela in page.extract_tables():
                    for row in tabela:
                        if not row or len(row) < 3:
                            continue

                        # Colunas: [Liq, Mov, Histórico, '', Valor, Saldo]
                        # Liq = data liquidação, Mov = data movimento
                        data_raw  = str(row[0] or "").strip()
                        desc_raw  = str(row[2] or "").strip()
                        # Valor pode estar na col 4 ou 3 dependendo da tabela
                        valor_raw = ""
                        for ci in (4, 3):
                            if ci < len(row) and row[ci]:
                                v = str(row[ci]).replace("R$", "").strip()
                                if re.search(r"\d", v):
                                    valor_raw = v
                                    break

                        if not data_raw or not desc_raw or not valor_raw:
                            continue

                        desc_up = desc_raw.upper()
                        if any(ig in desc_up for ig in IGNORAR):
                            continue
                        if "data" in data_raw.lower():
                            continue

                        data = converter_data(data_raw)
                        if data is None:
                            continue

                        valor = converter_valor(valor_raw)
                        if valor == 0.0:
                            continue

                        lancamentos.append({
                            "data_extrato":   pd.Timestamp(data),
                            "descricao":      desc_raw,
                            "descricao_norm": normalizar_texto(desc_raw),
                            "valor_extrato":  abs(valor),
                            "tipo":           "D" if valor < 0 else "C",
                            "documento":      "",
                            "documento_norm": "",
                            "used":           False,
                        })

        return self._montar_df(lancamentos)

    # -------------------------------------------------------------------------
    # HELPER: monta DataFrame final padronizado
    # -------------------------------------------------------------------------
    def _montar_df(self, lancamentos: list) -> pd.DataFrame:
        """Monta DataFrame padronizado a partir de lista de dicts."""
        if not lancamentos:
            logger.warning("⚠️ Nenhum lançamento encontrado no PDF.")
            return pd.DataFrame(columns=[
                "data_extrato", "descricao", "descricao_norm",
                "valor_extrato", "tipo", "documento", "documento_norm", "used"
            ])
        df = pd.DataFrame(lancamentos)
        df["data_extrato"] = pd.to_datetime(df["data_extrato"], errors="coerce")
        df.reset_index(drop=True, inplace=True)
        return df

    # -------------------------------------------------------------------------
    # PARSER BANCO DO BRASIL — tabela 8 colunas
    # Colunas: [dt_balancete, ?, ag, lote, histórico, documento, valor+D/C, saldo]
    # Valor e tipo juntos na col 6: '73,80 D' ou '11.000,00 C'
    # -------------------------------------------------------------------------
    def _ler_pdf_bb(self, caminho: Path) -> pd.DataFrame:
        """Lê extrato PDF do Banco do Brasil."""
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("pip install pdfplumber")

        IGNORAR_HIST = {
            "SALDO", "SALDO ANTERIOR", "SALDO FINAL", "S A L D O",
            "TOTAL", "LANÇAMENTOS", "LANCAMENTOS", "DT.", "HISTORICO",
            "BB RENDE", "RENDE FACIL",
        }
        VALOR_RE = re.compile(r"^([\d\.]+,[\d]{2})\s+([DC])$")

        lancamentos = []

        with pdfplumber.open(caminho) as pdf:
            texto_p1 = pdf.pages[0].extract_text() or ""
            m = re.search(r"Conta\s+corrente\s+([\d]+\-[\d]+)", texto_p1, re.IGNORECASE)
            if m:
                self.conta = m.group(1)
            m = re.search(r"Ag[eê]ncia\s+([\d\-]+)", texto_p1, re.IGNORECASE)
            if m:
                self.agencia = m.group(1)
            m = re.search(r"Per[ií]odo\s+do\s+extrato[^\n]*\n([^\n]+)", texto_p1, re.IGNORECASE)
            if not m:
                m = re.search(r"(\d{2}\s*/\s*\d{4})", texto_p1)
            if m:
                self.periodo = m.group(1).strip()

            # Tenta extrair ano do texto
            anos = re.findall(r"(20\d{2})", texto_p1)
            ano = int(anos[0]) if anos else pd.Timestamp.now().year

            for page in pdf.pages:
                tabelas = page.extract_tables()
                for tabela in tabelas:
                    for row in tabela:
                        if not row or len(row) < 7:
                            continue

                        data_raw  = str(row[0] or "").strip()
                        hist_raw  = str(row[4] or "").strip()
                        doc_raw   = str(row[5] or "").strip()
                        valor_raw = str(row[6] or "").strip()

                        # Ignora linhas sem data DD/MM/YYYY
                        if not re.match(r"\d{2}/\d{2}/\d{4}$", data_raw):
                            continue

                        # Ignora totalizadores
                        hist_up = hist_raw.upper()
                        if not hist_raw or any(ig in hist_up for ig in IGNORAR_HIST):
                            continue

                        # Histórico pode ter lote colado: '435 Tarifa Pacote...'
                        # Remove número inicial do lote se existir
                        hist_limpo = re.sub(r"^\d+\s+", "", hist_raw).strip()

                        data = converter_data(data_raw)
                        if data is None:
                            continue

                        # Valor: '73,80 D' ou '11.000,00 C'
                        m_val = VALOR_RE.match(valor_raw)
                        if not m_val:
                            # Tenta na col 7 (saldo às vezes vem junto)
                            valor_raw2 = str(row[7] or "").strip() if len(row) > 7 else ""
                            m_val = VALOR_RE.match(valor_raw2)
                            if not m_val:
                                continue

                        valor = converter_valor(m_val.group(1))
                        tipo  = m_val.group(2)  # 'D' ou 'C'

                        if valor == 0.0:
                            continue

                        lancamentos.append({
                            "data_extrato":   pd.Timestamp(data),
                            "descricao":      hist_limpo,
                            "descricao_norm": normalizar_texto(hist_limpo),
                            "valor_extrato":  abs(valor),
                            "tipo":           tipo,
                            "documento":      doc_raw,
                            "documento_norm": normalizar_texto(doc_raw),
                            "used":           False,
                        })

        return self._montar_df(lancamentos)

    # -------------------------------------------------------------------------
    # PARSER SANTANDER — Extrato Consolidado PJ PDF
    #
    # Formato real:
    #   Cabeçalho: "Agência Conta Corrente" → "0389 13.003819-7"
    #   Bloco de data: linha iniciando com "DD/MM DESCRICAO [ndoc] valor"
    #   ou linhas sem data pertencendo ao mesmo dia
    #   Créditos: valor sem sinal ou com "-" no final → débito
    #   Linha de detalhe (nome do favorecido) segue a transação
    # -------------------------------------------------------------------------
    def _ler_pdf_santander(self, caminho: Path) -> pd.DataFrame:
        """Lê extrato PDF do Santander (Extrato Consolidado PJ)."""
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("pip install pdfplumber")

        # DD/MM no início da linha — data sem ano
        DATA_RE  = re.compile(r"^(\d{2}/\d{2})\s+(.+)")
        # Valor monetário BR: 1.234,56 ou 234,56 podendo terminar em '-' p/ débito
        VALOR_RE = re.compile(r"([\d\.]+,\d{2})(-)?\.?$")
        IGNORAR  = {
            "SALDO", "TOTAL", "EXTRATO CONSOLIDADO", "MOVIMENTAÇÃO",
            "MOVIMENTACAO", "DATA DESCRIÇÃO", "DATA DESCRICAO",
            "CRÉDITOS", "CREDITOS", "DÉBITOS", "DEBITOS",
            "PAGINA", "PÁGINA", "LOJA:", "FALE CONOSCO",
            "CENTRAL DE ATENDIMENTO", "RESUMO", "NOME",
            "AGÊNCIA CONTA CORRENTE", "AGENCIA CONTA CORRENTE",
            "(=) SALDO", "(+) SALDO", "SOLUÇÕES", "SOLUCOES",
            "PREZADO", "EXTRATO_PJ", "BALP_",
        }

        lancamentos = []
        ano = None

        with pdfplumber.open(caminho) as pdf:
            # ── Extrai metadados do texto completo das 3 primeiras páginas
            for pg_idx in range(min(3, len(pdf.pages))):
                txt = pdf.pages[pg_idx].extract_text() or ""
                if not self.nome_conta:
                    m = re.search(r"Nome\s*\n([^\n]+)", txt)
                    if m:
                        self.nome_conta = m.group(1).strip()
                if not self.agencia or not self.conta:
                    m = re.search(r"(\d{3,4})\s+(\d{2}\.\d{6}-\d)", txt)
                    if m:
                        self.agencia = m.group(1)
                        self.conta   = m.group(2)
                if not ano:
                    m = re.search(r"(\d{4})(?:/|\.|-|\s)", txt)
                    if m:
                        ano = int(m.group(1))
                if not self.periodo:
                    m = re.search(r"(janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)/?(\d{4})", txt, re.IGNORECASE)
                    if m:
                        self.periodo = m.group(0)
                        if not ano:
                            ano = int(m.group(2))

            if not ano:
                ano = pd.Timestamp.now().year

            data_atual = None
            desc_pendente = ""   # linha de detalhe após transação

            for page in pdf.pages:
                texto = page.extract_text() or ""
                linhas = texto.split("\n")

                for linha in linhas:
                    linha = linha.strip()
                    if not linha:
                        continue

                    linha_up = linha.upper()

                    # Ignora cabeçalhos/rodapés
                    if any(ig in linha_up for ig in IGNORAR):
                        continue
                    # Linha só de números (totais, referência)
                    if re.match(r"^[\d\./\-\s]+$", linha) and len(linha) < 20:
                        continue

                    # ── Linha com data DD/MM
                    m_data = DATA_RE.match(linha)
                    if m_data:
                        data_str = m_data.group(1) + f"/{ano}"
                        data_atual = converter_data(data_str)
                        resto = m_data.group(2).strip()
                    else:
                        resto = linha

                    if data_atual is None:
                        continue

                    # ── Tenta extrair valor do final da linha
                    m_val = VALOR_RE.search(resto)
                    if not m_val:
                        # Pode ser linha de detalhe (nome favorecido, nº doc auxiliar)
                        # Acumula como desc_pendente para o próximo lançamento
                        desc_pendente = linha
                        continue

                    valor_str  = m_val.group(1)
                    eh_debito  = bool(m_val.group(2))   # termina em '-'
                    valor      = converter_valor(valor_str)
                    if valor == 0.0:
                        continue

                    # Remove o valor do texto
                    desc_bruta = resto[:m_val.start()].strip()

                    # Detecta débito pelo sufixo '-' OU por palavras-chave
                    desc_up = desc_bruta.upper()
                    if not eh_debito:
                        DEBITO_PALAVRAS = {
                            "PAGAMENTO", "DÉBITO", "DEBITO", "SAQUE", "TARIFA",
                            "TAXA", "PGTO", "APLICACAO", "APLICAÇÃO", "IOF",
                            "TED PGTO", "PIX ENVIADO", "ENVIADO",
                            "DEBITO AUT", "TRANSF", "PGTO FORNEC",
                        }
                        eh_debito = any(p in desc_up for p in DEBITO_PALAVRAS)

                    tipo = "D" if eh_debito else "C"

                    # Extrai nº documento (sequência numérica após descrição)
                    doc_match = re.search(r"\b(\d{4,})\b", desc_bruta)
                    doc_raw   = doc_match.group(1) if doc_match else ""

                    # Limpa descrição: remove o nº documento da descrição
                    desc = desc_bruta
                    if doc_raw:
                        desc = desc.replace(doc_raw, "").strip()
                    desc = re.sub(r"\s{2,}", " ", desc).strip()

                    # Acrescenta linha de detalhe pendente se existir
                    if desc_pendente:
                        desc = (desc + " " + desc_pendente).strip()
                        desc_pendente = ""

                    if not desc:
                        desc = desc_bruta

                    lancamentos.append({
                        "data_extrato":   pd.Timestamp(data_atual),
                        "descricao":      desc,
                        "descricao_norm": normalizar_texto(desc),
                        "valor_extrato":  abs(valor),
                        "tipo":           tipo,
                        "documento":      doc_raw,
                        "documento_norm": normalizar_texto(doc_raw),
                        "used":           False,
                    })
                    desc_pendente = ""

        return self._montar_df(lancamentos)

    # -------------------------------------------------------------------------
    # PARSER BRADESCO — texto livre
    #
    # Formato real do PDF Bradesco:
    #   Linha com data   → DD/MM/YYYY HISTORICO [DOC] [CREDITO] [SALDO]
    #   Linha sem data   → HISTORICO DOC DEBITO SALDO   (lançamentos do mesmo dia)
    #   Linha de detalhe → REM: ... (complemento do lançamento anterior)
    #
    # Colunas: Data | Lançamento | Dcto. | Crédito (R$) | Débito (R$) | Saldo (R$)
    # Débitos têm sinal negativo, créditos são positivos.
    # -------------------------------------------------------------------------
    def _ler_pdf_bradesco(self, caminho: Path) -> pd.DataFrame:
        """Lê extrato PDF do Bradesco."""
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("pip install pdfplumber")

        IGNORAR_HIST = {
            "SALDO ANTERIOR", "SALDO FINAL", "TOTAL", "DATA LANÇAMENTO",
            "DATA LANCAMENTO", "SALDOS INVEST", "SALDO INVEST",
            "OS DADOS ACIMA", "ÚLTIMOS LANÇAMENTOS", "ULTIMOS LANCAMENTOS",
            "EXTRATO MENSAL",
        }

        DATA_RE  = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(.*)")
        VALOR_RE = re.compile(r"(-?[\d\.]+,\d{2})")

        lancamentos = []

        with pdfplumber.open(caminho) as pdf:
            # Metadados
            texto_p1 = pdf.pages[0].extract_text() or ""
            m = re.search(r"(\d{4,5})\s*\|\s*([\d\-]+)", texto_p1)
            if m:
                self.agencia = m.group(1)
                self.conta   = m.group(2)
            m = re.search(r"Entre\s+(\d{2}/\d{2}/\d{4})\s+e\s+(\d{2}/\d{2}/\d{4})", texto_p1, re.IGNORECASE)
            if m:
                self.periodo = f"{m.group(1)} a {m.group(2)}"

            data_atual = None

            for page in pdf.pages:
                texto = page.extract_text() or ""
                # Pula página de saldos de investimento (página 2+)
                if "Saldos Invest" in texto or "SALDO INVEST FÁCIL" in texto:
                    continue

                linhas = texto.split("\n")
                i = 0
                while i < len(linhas):
                    linha = linhas[i].strip()
                    i += 1

                    if not linha:
                        continue

                    # Ignora cabeçalhos e rodapés
                    linha_up = linha.upper()
                    if any(ig in linha_up for ig in IGNORAR_HIST):
                        continue
                    if linha_up.startswith("DATA") and "LANÇAMENTO" in linha_up:
                        continue
                    if linha_up.startswith("EXTRATO") or linha_up.startswith("AFRIKA"):
                        continue
                    if linha_up.startswith("NOME DO USUÁRIO") or linha_up.startswith("DATA DA OPERAÇÃO"):
                        continue
                    if linha_up.startswith("AGÊNCIA") or linha_up.startswith("OS DADOS"):
                        continue

                    # ── Linha de detalhe (REM:, CONTR, etc.) — complemento do anterior
                    if linha_up.startswith("REM:") or linha_up.startswith("CONTR "):
                        if lancamentos:
                            lancamentos[-1]["descricao"] += " | " + linha
                        continue

                    # ── Linha com data: DD/MM/YYYY ...
                    m_data = DATA_RE.match(linha)
                    if m_data:
                        data_atual = converter_data(m_data.group(1))
                        resto = m_data.group(2).strip()
                    else:
                        # Linha sem data: lançamento extra do mesmo dia
                        resto = linha

                    if data_atual is None:
                        continue

                    # Extrai valores monetários da linha
                    valores_str = VALOR_RE.findall(resto)
                    if not valores_str:
                        continue

                    # Remove os valores do texto para ficar só a descrição
                    desc = VALOR_RE.sub("", resto).strip()
                    desc = re.sub(r"\s{2,}", " ", desc).strip()

                    # Extrai documento (sequência de 4+ dígitos que sobrou na descrição)
                    doc_match = re.search(r"\b(\d{4,})\b", desc)
                    doc_raw   = doc_match.group(1) if doc_match else ""
                    if doc_raw:
                        desc = desc.replace(doc_raw, "").strip()
                    desc = re.sub(r"\s{2,}", " ", desc).strip()

                    # Se a descrição ficou vazia após remover o doc, usa 'TRANSFERENCIA PIX'
                    # (linhas tipo: '03/01/2025 1849513 28.200,00 62,60')
                    if not desc:
                        # Olha a linha anterior para pegar o histórico
                        desc = "TRANSFERENCIA PIX"

                    # Converte valores: último é sempre saldo
                    nums = [converter_valor(v) for v in valores_str]

                    # Remove zeros e saldo (último)
                    candidatos = nums[:-1] if len(nums) > 1 else nums

                    valor_num = None
                    for v in candidatos:
                        if v != 0.0:
                            valor_num = v
                            break

                    if valor_num is None:
                        continue

                    tipo = "D" if valor_num < 0 else "C"

                    lancamentos.append({
                        "data_extrato":   pd.Timestamp(data_atual),
                        "descricao":      desc,
                        "descricao_norm": normalizar_texto(desc),
                        "valor_extrato":  abs(valor_num),
                        "tipo":           tipo,
                        "documento":      doc_raw,
                        "documento_norm": normalizar_texto(doc_raw),
                        "used":           False,
                    })

        return self._montar_df(lancamentos)

    def _ler_pdf_itau(self, caminho: Path) -> pd.DataFrame:
        """
        Lê extrato PDF do Itaú via pdfplumber.

        Estrutura das tabelas no PDF:
            [data, descrição, '', '', valor, '']
        Data formato: '02 / jan' ou '02/01/2025'
        Valor: '-1.234,56' ou '1.234,56'
        """
        try:
            import pdfplumber
        except ImportError:
            raise ImportError(
                "pdfplumber é necessário para ler PDFs. "
                "Instale com: pip install pdfplumber"
            )

        MESES_PT = {
            "jan": 1, "fev": 2, "mar": 3, "abr": 4,
            "mai": 5, "jun": 6, "jul": 7, "ago": 8,
            "set": 9, "out": 10, "nov": 11, "dez": 12,
        }

        lancamentos = []

        with pdfplumber.open(caminho) as pdf:
            # Extrai metadados e determina o ano a partir do texto do PDF
            texto_p1 = pdf.pages[0].extract_text() or ""
            m = re.search(r"Conta[:\s]*(\d[\d\-\.]+)", texto_p1, re.IGNORECASE)
            if m:
                self.conta = m.group(1)
            m = re.search(r"Ag[eê]ncia[:\s]*(\d+)", texto_p1, re.IGNORECASE)
            if m:
                self.agencia = m.group(1)

            # Tenta extrair ano/mês do texto do PDF (ex: "Período: 01/01/2025 a 31/01/2025")
            ano = None
            mes_arquivo = None
            # Busca padrão de data completa no texto (DD/MM/AAAA)
            datas_no_texto = re.findall(r"\d{2}/\d{2}/(20\d{2})", texto_p1)
            if datas_no_texto:
                ano = int(datas_no_texto[0])
                # Pega o mês da primeira data encontrada
                meses_no_texto = re.findall(r"\d{2}/(\d{2})/20\d{2}", texto_p1)
                if meses_no_texto:
                    mes_arquivo = int(meses_no_texto[0])
            # Fallback: tenta extrair do nome do arquivo (quando não é tmp)
            if not ano:
                ano_match = re.search(r"(20\d{2})", caminho.stem)
                ano = int(ano_match.group(1)) if ano_match else None
                mes_match = re.search(r"20\d{2}(\d{2})", caminho.stem)
                mes_arquivo = int(mes_match.group(1)) if mes_match else None
            # Último fallback: ano atual (nunca deve chegar aqui)
            if not ano:
                logger.warning("⚠️ Ano não detectado no PDF — usando ano atual")
                ano = pd.Timestamp.now().year

            for page in pdf.pages:
                tabelas = page.extract_tables()
                for tabela in tabelas:
                    for row in tabela:
                        if not row or len(row) < 5:
                            continue

                        data_raw = str(row[0] or "").strip()
                        desc_raw = str(row[1] or "").strip()
                        # Valor geralmente na col 4 (idx 4)
                        valor_raw = str(row[4] or "").strip()

                        if not data_raw or not valor_raw:
                            continue

                        # Converte data: '02 / jan' → date
                        data = None
                        # Formato '02 / jan' ou '02/jan'
                        m = re.match(
                            r"(\d{1,2})\s*/\s*([a-z]{3})",
                            data_raw.lower()
                        )
                        if m:
                            dia = int(m.group(1))
                            mes = MESES_PT.get(m.group(2), mes_arquivo or 1)
                            # Dezembro do ano anterior pode aparecer no extrato de jan
                            ano_real = ano
                            try:
                                data = pd.Timestamp(ano_real, mes, dia)
                            except Exception:
                                continue
                        else:
                            data = converter_data(data_raw)
                            if data is pd.NaT:
                                continue

                        # Ignora totalizadores
                        desc_upper = desc_raw.upper()
                        if any(ig in desc_upper for ig in self.IGNORAR_DESCRICAO):
                            continue
                        if not desc_raw:
                            continue

                        valor = converter_valor(valor_raw)
                        if valor == 0.0:
                            continue

                        lancamentos.append({
                            "data_extrato":   data,
                            "descricao":      desc_raw,
                            "descricao_norm": normalizar_texto(desc_raw),
                            "valor_extrato":  abs(valor),
                            "tipo":           "D" if valor < 0 else "C",
                            "documento":      "",
                            "documento_norm": "",
                            "used":           False,
                        })

        if not lancamentos:
            # Fallback: tenta o formato novo do Itaú (texto corrido, sem tabelas)
            logger.info("⚠️ Tabelas vazias — tentando formato texto corrido (Itaú novo)")
            return self._ler_pdf_itau_texto(caminho)

        df = pd.DataFrame(lancamentos)
        df["data_extrato"] = pd.to_datetime(df["data_extrato"], errors="coerce")
        df.reset_index(drop=True, inplace=True)
        return df

    # -------------------------------------------------------------------------
    # PARSER ITAÚ FORMATO NOVO (set/2025+) — texto corrido, sem tabelas
    #
    # Formato: cada linha é um lançamento completo:
    #   DD/MM/AAAA HISTÓRICO [RAZÃO SOCIAL] [CNPJ/CPF] VALOR SALDO
    #   Linhas de continuação: apenas texto (razão social) sem data
    #   Linhas de saldo do dia: "DD/MM/AAAA SALDO TOTAL DISPONÍVEL DIA VALOR"
    #   Valor negativo = Débito | positivo = Crédito
    # -------------------------------------------------------------------------
    def _ler_pdf_itau_texto(self, caminho: Path) -> pd.DataFrame:
        """Lê extrato PDF do Itaú no formato novo (texto corrido, set/2025+)."""
        try:
            import pdfplumber
        except ImportError:
            raise ImportError("pip install pdfplumber")

        IGNORAR = {
            "SALDO ANTERIOR", "SALDO FINAL", "SALDO TOTAL DISPONÍVEL DIA",
            "SALDO TOTAL DISPONIVEL DIA", "LANÇAMENTOS DO PERÍODO",
            "LANCAMENTOS DO PERIODO", "DATA LANÇAMENTOS",
        }

        DATA_RE  = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(.*)")
        VALOR_RE = re.compile(r"(-?[\d\.]+,\d{2})")
        CNPJ_RE  = re.compile(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{3}\.\d{3}\.\d{3}-\d{2}")

        lancamentos = []

        with pdfplumber.open(caminho) as pdf:
            texto_p1 = pdf.pages[0].extract_text() or ""
            # Metadados — formato: "EMPRESA CNPJ xx Agência 0264 Conta 0038673-1"
            m = re.search(r"Conta\s+([\d]+[\d\-]+)", texto_p1, re.IGNORECASE)
            if m:
                self.conta = m.group(1)
            m = re.search(r"Ag[eê]ncia\s+(\d+)", texto_p1, re.IGNORECASE)
            if m:
                self.agencia = m.group(1)
            m = re.search(r"(\d{2}/\d{2}/\d{4})\s+até\s+(\d{2}/\d{2}/\d{4})", texto_p1, re.IGNORECASE)
            if m:
                self.periodo = f"{m.group(1)} a {m.group(2)}"

            for page in pdf.pages:
                texto = page.extract_text() or ""
                linhas = texto.split("\n")
                i = 0
                while i < len(linhas):
                    linha = linhas[i].strip()
                    i += 1

                    if not linha:
                        continue

                    m_data = DATA_RE.match(linha)
                    if not m_data:
                        continue

                    data_str = m_data.group(1)
                    resto    = m_data.group(2).strip()

                    # Ignora linhas de saldo do dia e cabeçalhos
                    resto_up = resto.upper()
                    if any(ig in resto_up for ig in IGNORAR):
                        continue

                    data = converter_data(data_str)
                    if data is None:
                        continue

                    # Extrai valores: último = saldo, penúltimo = valor do lançamento
                    valores_str = VALOR_RE.findall(resto)
                    if not valores_str:
                        continue

                    # Remove valores e CNPJ/CPF do texto → fica só o histórico
                    desc = VALOR_RE.sub("", resto)
                    desc = CNPJ_RE.sub("", desc)
                    desc = re.sub(r"\s{2,}", " ", desc).strip()

                    if not desc:
                        continue

                    # Pega linha seguinte se for continuação (Razão Social)
                    if i < len(linhas):
                        prox = linhas[i].strip()
                        # Continuação: linha sem data, sem valor, não é cabeçalho
                        if prox and not DATA_RE.match(prox) and not VALOR_RE.search(prox):
                            prox_up = prox.upper()
                            if not any(ig in prox_up for ig in IGNORAR):
                                desc = desc + " " + prox
                                i += 1

                    desc = re.sub(r"\s{2,}", " ", desc).strip()

                    # Valor do lançamento = penúltimo se há 2+, senão o único
                    nums = [converter_valor(v) for v in valores_str]
                    valor_num = nums[-2] if len(nums) >= 2 else nums[0] if nums else 0.0

                    if valor_num == 0.0:
                        continue

                    tipo = "D" if valor_num < 0 else "C"

                    lancamentos.append({
                        "data_extrato":   pd.Timestamp(data),
                        "descricao":      desc,
                        "descricao_norm": normalizar_texto(desc),
                        "valor_extrato":  abs(valor_num),
                        "tipo":           tipo,
                        "documento":      "",
                        "documento_norm": "",
                        "used":           False,
                    })

        return self._montar_df(lancamentos)

    def _extrair_metadados_excel(self, df_raw: pd.DataFrame):
        """Extrai Nome, Agência, Conta e Período do cabeçalho do Excel do Itaú."""
        for _, row in df_raw.iterrows():
            vals = [str(v).strip() for v in row.tolist()]
            if not any(vals): continue
            linha = vals[0].lower()
            if "nome:" in linha or linha == "nome:":
                self.nome_conta = vals[1] if len(vals) > 1 else ""
            elif "agência:" in linha or "agencia:" in linha:
                self.agencia = vals[1] if len(vals) > 1 else ""
            elif "conta:" in linha:
                self.conta = vals[1] if len(vals) > 1 else ""
            elif "periodo:" in linha or "período:" in linha:
                self.periodo = vals[1] if len(vals) > 1 else ""

    def _ler_html_xls(self, caminho: Path) -> pd.DataFrame:
        """
        Parser rápido para .xls que são HTML (formato BB).
        Usa regex direto no HTML — evita pd.read_html que trava com 3000+ tabelas.

        Estrutura por linha <tr> com 9 <td>:
          0=Data  1=Descrição  2=LC Contábil  3=Cheque  4=Débito  5=Crédito
          6=Doc/Parc  7=N.Solicitação
        """
        with open(str(caminho), encoding="latin-1", errors="replace") as f:
            html = f.read()

        self.banco = "Banco do Brasil"

        # Extrai metadados do cabeçalho
        m = re.search(r"CAgencia/Conta\s*([\d\-/]+)", html, re.IGNORECASE)
        if m:
            partes = m.group(1).split("/")
            self.agencia = partes[0].strip()
            self.conta   = partes[-1].strip()
        m = re.search(r"<b>([A-Z][A-Z\s]{5,}LTDA[^<]*)</b>", html, re.IGNORECASE)
        if m:
            self.nome_conta = m.group(1).strip()

        # Remove tags HTML de cada célula
        _re_tag = re.compile(r"<[^>]+>")
        def _limpar(txt: str) -> str:
            return _re_tag.sub("", txt).strip()

        # Extrai todas as linhas <tr>...</tr>
        _re_tr  = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
        _re_td  = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
        _re_dia = re.compile(r"^\d{2}/\d{2}$")

        IGNORAR_DESC = {
            "CREDITO CARTAO ACORDO CIELO", "DEBITO SERVICO COBRANCA",
            "SALDO ANTERIOR", "SALDO FINAL", "SALDO TOTAL", "TOTAL DO DIA",
            "SALDO", "DATA", "HISTORICO", "HISTÓRICO",
        }

        lancamentos = []

        for tr_match in _re_tr.finditer(html):
            tr_html = tr_match.group(1)
            tds = [_limpar(td.group(1)) for td in _re_td.finditer(tr_html)]

            if len(tds) < 6:
                continue

            data_raw = tds[0]
            if not _re_dia.match(data_raw):
                continue

            descricao = tds[1]
            if not descricao or descricao.upper() in IGNORAR_DESC:
                continue

            debito_raw  = tds[4] if len(tds) > 4 else ""
            credito_raw = tds[5] if len(tds) > 5 else ""
            doc         = tds[6] if len(tds) > 6 else ""

            debito  = converter_valor(debito_raw)  if debito_raw  else 0.0
            credito = converter_valor(credito_raw) if credito_raw else 0.0

            if debito > 0 and credito == 0:
                valor = debito
                tipo  = "D"
            elif credito > 0 and debito == 0:
                valor = credito
                tipo  = "C"
            elif debito > 0 and credito > 0:
                valor = credito
                tipo  = "C"
            else:
                continue

            # Completa ano: DD/MM → DD/MM/YYYY usando ano do arquivo (ou atual)
            import datetime
            ano = datetime.date.today().year
            data_full = f"{data_raw}/{ano}"
            data = converter_data(data_full)
            if data is pd.NaT:
                continue

            lancamentos.append({
                "data_extrato":   pd.Timestamp(data),
                "descricao":      descricao,
                "descricao_norm": normalizar_texto(descricao),
                "valor_extrato":  abs(valor),
                "tipo":           tipo,
                "documento":      doc,
                "documento_norm": normalizar_texto(doc),
                "used":           False,
            })

        if not lancamentos:
            raise ValueError("Nenhum lançamento encontrado no arquivo HTML-XLS.")

        logger.info(f"✅ HTML-XLS BB: {len(lancamentos)} lançamentos")
        return self._montar_df(lancamentos)

    def _ler_csv(self, caminho: Path) -> pd.DataFrame:
        """
        Lê arquivo CSV testando separadores e encodings comuns.
        """
        encodings = ["utf-8-sig", "latin-1", "cp1252"]
        separadores = [";", ",", "\t"]

        for encoding in encodings:
            for sep in separadores:
                try:
                    # Primeira leitura rápida para detectar cabeçalho
                    df_raw = pd.read_csv(caminho, header=None, sep=sep,
                                         dtype=str, encoding=encoding, nrows=20)
                    if df_raw.shape[1] < 2:
                        continue

                    df_raw.fillna("", inplace=True)
                    linha_header = self._encontrar_linha_cabecalho(df_raw)

                    df = pd.read_csv(caminho, header=linha_header, sep=sep,
                                     dtype=str, encoding=encoding)
                    df.fillna("", inplace=True)
                    logger.debug(f"✅ CSV lido com sep='{sep}', encoding='{encoding}'")
                    return df
                except Exception:
                    continue

        raise ValueError("Não foi possível ler o CSV com os formatos testados.")

    def _encontrar_linha_cabecalho(self, df_raw: pd.DataFrame) -> int:
        """
        Encontra a linha que contém o cabeçalho da tabela de lançamentos.
        Procura por palavras-chave como 'data', 'valor', 'descrição'.
        """
        palavras_chave = {"data", "valor", "descricao", "descrição", "historico",
                          "histórico", "lancamento", "lançamento"}

        for i, row in df_raw.iterrows():
            linha_str = " ".join(str(v).lower() for v in row.values)
            matches = sum(1 for p in palavras_chave if p in linha_str)
            if matches >= 2:
                return i

        return 0  # Se não encontrou, assume que é a primeira linha

    # -------------------------------------------------------------------------
    # MAPEAMENTO DE COLUNAS
    # -------------------------------------------------------------------------
    def _mapear_colunas(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Mapeia as colunas do arquivo para os campos padronizados.
        Detecta automaticamente o formato Itaú (Lançamento + Razão Social)
        e formatos genéricos via aliases.
        """
        colunas_norm = {
            col: remover_acentos(str(col)).lower().strip()
            for col in df.columns
        }

        self._mapa_indices = {}
        for campo, aliases in self.MAPA_COLUNAS.items():
            for col_original, col_norm in colunas_norm.items():
                if any(alias in col_norm for alias in aliases):
                    self._mapa_indices[campo] = col_original
                    break

        logger.debug(f"📋 Mapeamento: {self._mapa_indices}")

        if "data" not in self._mapa_indices:
            raise ValueError("❌ Coluna de DATA não encontrada no extrato.")
        if "valor" not in self._mapa_indices:
            raise ValueError("❌ Coluna de VALOR não encontrada no extrato.")

        df_mapeado = pd.DataFrame()
        df_mapeado["data_extrato"] = df[self._mapa_indices["data"]]

        # ── Formato Itaú: mescla 'Lançamento' + 'Razão Social' como descrição ──
        col_lanc  = self._mapa_indices.get("descricao")
        col_razao = next((c for c, n in colunas_norm.items()
                          if "razao social" in n or "razão social" in n), None)
        if col_lanc and col_razao:
            df_mapeado["descricao"] = df.apply(
                lambda r: " ".join(
                    p for p in [str(r[col_lanc]).strip(), str(r[col_razao]).strip()]
                    if p and p.lower() not in ("nan", "")
                ), axis=1
            )
        elif col_lanc:
            df_mapeado["descricao"] = df[col_lanc].astype(str)
        else:
            df_mapeado["descricao"] = ""

        # Coluna CPF/CNPJ como documento (Itaú)
        col_doc = self._mapa_indices.get("documento")
        if not col_doc:
            col_doc = next((c for c, n in colunas_norm.items()
                            if "cpf" in n or "cnpj" in n), None)
        df_mapeado["documento"] = df[col_doc].astype(str) if col_doc else ""

        df_mapeado["valor_extrato_raw"] = df[self._mapa_indices["valor"]]
        df_mapeado["tipo"] = df.get(self._mapa_indices.get("tipo"), "")

        return df_mapeado

    # -------------------------------------------------------------------------
    # FILTRAGEM
    # -------------------------------------------------------------------------
    def _filtrar_linhas_validas(self, df: pd.DataFrame) -> pd.DataFrame:
        """Remove linhas sem data, sem valor ou totalizadores de saldo."""
        # Converte datas
        df["data_extrato"] = df["data_extrato"].apply(converter_data)
        df = df[df["data_extrato"].notna()].copy()

        # Converte valores (mantém sinal para D/C)
        df["valor_extrato"] = df["valor_extrato_raw"].apply(converter_valor)

        # Remove linhas sem valor (ex: linhas de saldo do dia que só têm Saldo)
        df = df[df["valor_extrato"] != 0.0].copy()

        # Remove totalizadores pela descrição
        mask = df["descricao"].str.upper().apply(
            lambda d: any(ig in d for ig in self.IGNORAR_DESCRICAO)
        )
        df = df[~mask].copy()

        return df

    # -------------------------------------------------------------------------
    # NORMALIZAÇÃO FINAL
    # -------------------------------------------------------------------------
    def _normalizar_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normaliza texto, determina tipo D/C, limpa colunas."""
        df["descricao_norm"] = df["descricao"].apply(normalizar_texto)
        df["documento_norm"] = df["documento"].apply(normalizar_texto)

        # Tipo D/C baseado no sinal do valor
        df["tipo"] = df.apply(self._determinar_tipo, axis=1)

        # Valor absoluto para comparação (tipo já guarda a direção)
        df["valor_extrato"] = df["valor_extrato"].abs()

        df["data_extrato"] = pd.to_datetime(df["data_extrato"], errors="coerce")
        df["used"] = False
        df.drop(columns=["valor_extrato_raw"], inplace=True, errors="ignore")
        df.reset_index(drop=True, inplace=True)

        colunas_finais = [
            "data_extrato", "descricao", "descricao_norm",
            "valor_extrato", "tipo", "documento", "documento_norm", "used"
        ]
        return df[[c for c in colunas_finais if c in df.columns]]

    def _determinar_tipo(self, row) -> str:
        """
        Determina se o lançamento é Débito (D) ou Crédito (C).
        
        Lógica:
        1. Se coluna 'tipo' já tem D/C, usa ela
        2. Se valor original era negativo → Débito
        3. Se valor original era positivo → Crédito
        """
        tipo_raw = str(row.get("tipo", "")).upper().strip()

        # Detecta D/C direto na coluna tipo
        if tipo_raw in ["D", "DEB", "DEBITO", "DÉBITO", "DEBIT"]:
            return "D"
        if tipo_raw in ["C", "CRED", "CREDITO", "CRÉDITO", "CREDIT"]:
            return "C"

        # Usa o sinal do valor raw para determinar
        valor_raw = str(row.get("valor_extrato_raw", "0"))
        valor_num = converter_valor(valor_raw)
        if valor_num < 0:
            return "D"
        return "C"


# =============================================================================
# EXECUÇÃO DIRETA (para testar o parser isoladamente)
# =============================================================================
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG)

    caminho = sys.argv[1] if len(sys.argv) > 1 else \
              "/Users/eduardomassarente/Projeto_Lage/Itau_extrato  - 01-2026 - excell.xlsx"

    parser = ExtratoParser()
    df = parser.carregar(caminho)

    print("\n📊 EXTRATO CARREGADO:")
    print(df.to_string())
    meta = parser.obter_metadados()
    print(f"Nome   : {meta['nome']}")
    print(f"Agência: {meta['agencia']} | Conta: {meta['conta']}")
    print(f"Período: {meta['periodo']}")
    print(f"\nTotal  : {len(df)} lançamentos")
    print(f"Débitos: {len(df[df['tipo'] == 'D'])}")
    print(f"Créditos: {len(df[df['tipo'] == 'C'])}")
    print()
    print(df[["data_extrato","descricao","valor_extrato","tipo"]].to_string())
