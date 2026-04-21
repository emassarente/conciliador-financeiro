"""
Parser para extratos do C6 Bank em PDF (protegido ou não).
Formato: Data lançamento | Data contábil | Tipo | Descrição | Valor
"""
import re
import PyPDF2
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional


class C6BankParser:
    def __init__(self, pdf_path: str, senha: str = None):
        self.pdf_path = Path(pdf_path)
        self.senha = senha
        self.empresa_nome = None
        self.cnpj = None
        self.periodo_inicio = None
        self.periodo_fim = None
        self.lancamentos = []

    def parse(self) -> List[Dict]:
        """Extrai lançamentos do PDF do C6 Bank."""
        with open(self.pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            
            if reader.is_encrypted:
                if not self.senha:
                    raise ValueError("PDF protegido mas senha não fornecida")
                if not reader.decrypt(self.senha):
                    raise ValueError("Senha incorreta")
            
            texto_completo = ""
            for page in reader.pages:
                texto_completo += page.extract_text() + "\n"
        
        return self._processar_texto(texto_completo)

    def _processar_texto(self, texto: str) -> List[Dict]:
        """Processa o texto extraído e retorna lista de lançamentos."""
        linhas = texto.split("\n")
        
        # Extrai cabeçalho
        for i, linha in enumerate(linhas[:20]):
            # Empresa e CNPJ (ex: "G A S TRANSPORTES • 29.450.143/0001-87")
            if "•" in linha and re.search(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", linha):
                partes = linha.split("•")
                self.empresa_nome = partes[0].strip()
                cnpj_match = re.search(r"(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", partes[1])
                if cnpj_match:
                    self.cnpj = cnpj_match.group(1)
            
            # Período (ex: "Período • 1 de julho de 2025 até 31 de julho de 2025")
            if "Período" in linha and "até" in linha:
                periodo_match = re.search(
                    r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})\s+até\s+(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})",
                    linha
                )
                if periodo_match:
                    self.periodo_inicio = self._parse_data_extenso(
                        periodo_match.group(1), periodo_match.group(2), periodo_match.group(3)
                    )
                    self.periodo_fim = self._parse_data_extenso(
                        periodo_match.group(4), periodo_match.group(5), periodo_match.group(6)
                    )
        
        # Processa lançamentos — estratégia: busca por padrão DD/MM DD/MM Tipo ... R$
        lancamentos = []
        ano = self.periodo_inicio.year if self.periodo_inicio else datetime.now().year
        
        # Junta tudo em texto único e procura por padrão completo
        texto_limpo = re.sub(r'\s+', ' ', texto)  # Normaliza espaços
        
        # Regex que captura: data_lanc data_cont tipo descrição valor
        # Padrão: DD/MM DD/MM (Saída|Entrada|...) ... -?R$ X.XXX,XX
        padrao = r'(\d{2}/\d{2})\s+(\d{2}/\d{2})\s+(Saída|Saídas|Entrada|Entradas|Pagamento|Tarifa|Saldo)(?:\s+PIX|\s+em\s+lote)?\s+(.*?)\s+(-?R\$\s*[\d.,]+)'
        
        matches = re.finditer(padrao, texto_limpo)
        
        for match in matches:
            data_lanc = match.group(1)
            data_cont = match.group(2)
            tipo = match.group(3)
            descricao_raw = match.group(4).strip()
            valor_str = match.group(5)
            
            # Limpa descrição (remove possíveis quebras de padrão)
            descricao = re.sub(r'\s+', ' ', descricao_raw).strip()
            
            # Parse valor
            valor = self._parse_valor(valor_str)
            
            # Monta data completa
            data_completa = self._parse_data_curta(data_lanc, ano)
            
            lancamentos.append({
                "data": data_completa,
                "data_lancamento": data_lanc,
                "data_contabil": data_cont,
                "tipo": tipo,
                "descricao": descricao,
                "valor": valor,
                "natureza": "D" if valor < 0 else "C",
            })
        
        self.lancamentos = lancamentos
        return lancamentos

    def _parse_data_extenso(self, dia: str, mes_nome: str, ano: str) -> datetime:
        """Converte 'dia de mês de ano' para datetime."""
        meses = {
            "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4,
            "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
            "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12
        }
        mes = meses.get(mes_nome.lower(), 1)
        return datetime(int(ano), mes, int(dia))

    def _parse_data_curta(self, data_str: str, ano: int) -> str:
        """Converte DD/MM para YYYY-MM-DD."""
        dia, mes = data_str.split("/")
        return f"{ano}-{mes.zfill(2)}-{dia.zfill(2)}"

    def _parse_valor(self, valor_str: str) -> float:
        """Converte 'R$ 1.234,56' ou '-R$ 1.234,56' para float."""
        valor_str = valor_str.replace("R$", "").replace(" ", "").strip()
        negativo = valor_str.startswith("-")
        valor_str = valor_str.replace("-", "")
        valor_str = valor_str.replace(".", "").replace(",", ".")
        valor = float(valor_str)
        return -valor if negativo else valor

    def to_dataframe(self):
        """Retorna DataFrame pandas com os lançamentos."""
        import pandas as pd
        if not self.lancamentos:
            self.parse()
        return pd.DataFrame(self.lancamentos)


if __name__ == "__main__":
    # Teste
    pdf = Path(__file__).parent.parent / "data/extratos_gas/Extrato_Conta_Corrente_C6Bank_24_08_202524-08-2025-10_08_41.pdf"
    parser = C6BankParser(pdf, senha="294501")
    lancamentos = parser.parse()
    
    print(f"Empresa: {parser.empresa_nome}")
    print(f"CNPJ: {parser.cnpj}")
    print(f"Período: {parser.periodo_inicio} a {parser.periodo_fim}")
    print(f"Lançamentos: {len(lancamentos)}")
    print("\nPrimeiros 5:")
    for lanc in lancamentos[:5]:
        print(f"  {lanc['data']} | {lanc['descricao'][:40]:40} | {lanc['valor']:>12.2f}")
