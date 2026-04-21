# =============================================================================
# MOTOR DE CONCILIAÇÃO - MATCH EXATO (NÍVEL 1)
# Compara lançamentos do Razão com o Extrato bancário buscando:
# - Valor igual (tolerância de R$ 0,01 por arredondamento)
# - Diferença de data de até 3 dias corridos
#
# Resultado:
#   status      = CONCILIADO
#   confidence  = 100%
#   tipo_match  = EXATO
# =============================================================================

import logging
import pandas as pd
from typing import Tuple, List, Dict, Optional

logger = logging.getLogger(__name__)


class ExactMatch:
    """
    Realiza o MATCH EXATO (Nível 1) da engine de conciliação.
    
    Regras:
    - O valor do lançamento do Razão deve ser igual ao valor do Extrato
      (tolerância de 0,01 para diferenças de arredondamento)
    - A diferença entre as datas deve ser no máximo 3 dias corridos
    - Cada lançamento só pode ser usado UMA vez (flag used=True)
    
    Por que 3 dias?
        Alguns lançamentos bancários aparecem com datas diferentes
        no extrato e no razão contábil por causa de:
        - Fuso horário do sistema
        - Data de compensação vs data do lançamento
        - Finais de semana e feriados
    """

    # Sem tolerância: o valor deve bater exatamente (diferença de R$0,01 pode ser multa/juros)
    TOLERANCIA_VALOR = 0.00

    # Tolerância em dias para comparação de datas
    TOLERANCIA_DIAS = 3

    def __init__(self):
        pass

    def executar(
        self,
        df_razao: pd.DataFrame,
        df_extrato: pd.DataFrame
    ) -> Tuple[pd.DataFrame, pd.DataFrame, List[Dict]]:
        """
        Executa o match exato entre todos os lançamentos disponíveis.
        
        Args:
            df_razao:   DataFrame do Razão (com coluna 'used')
            df_extrato: DataFrame do Extrato (com coluna 'used')
            
        Returns:
            Tupla com:
            - df_razao atualizado (lançamentos usados marcados)
            - df_extrato atualizado (lançamentos usados marcados)
            - Lista de matches encontrados (dicionários)
        """
        matches = []
        total_razao = len(df_razao[~df_razao["used"]])
        logger.info(f"🔍 Iniciando Match Exato | Razão: {total_razao} lançamentos disponíveis")

        # Itera apenas sobre lançamentos do Razão que ainda não foram usados
        for idx_razao, row_razao in df_razao[~df_razao["used"]].iterrows():

            # Busca o melhor candidato no extrato
            resultado = self._buscar_par_extrato(row_razao, df_extrato)

            if resultado is not None:
                idx_extrato, row_extrato = resultado

                # Marca ambos como usados para não serem reutilizados
                df_razao.at[idx_razao, "used"] = True
                df_extrato.at[idx_extrato, "used"] = True

                # Registra o match
                match = self._criar_registro_match(
                    idx_razao, row_razao,
                    idx_extrato, row_extrato
                )
                matches.append(match)
                logger.debug(
                    f"✅ Match Exato: Razão[{idx_razao}] R${row_razao['valor_razao']:.2f} "
                    f"← Extrato[{idx_extrato}] R${row_extrato['valor_extrato']:.2f}"
                )

        encontrados = len(matches)
        logger.info(f"✅ Match Exato concluído: {encontrados} conciliações encontradas.")
        return df_razao, df_extrato, matches

    # -------------------------------------------------------------------------
    # BUSCA DO PAR NO EXTRATO
    # -------------------------------------------------------------------------
    def _buscar_par_extrato(
        self,
        row_razao: pd.Series,
        df_extrato: pd.DataFrame
    ) -> Optional[Tuple[int, pd.Series]]:
        """
        Para um lançamento do Razão, busca o melhor par no Extrato.
        
        Critérios (em ordem de prioridade):
        1. Valor igual (dentro da tolerância)
        2. Menor diferença de data (máximo 3 dias)
        
        Returns:
            Tupla (índice, linha) do melhor par encontrado, ou None
        """
        valor_razao = abs(row_razao["valor_razao"])
        data_razao = row_razao["data_razao"]

        # Filtra candidatos no extrato: apenas não usados
        candidatos = df_extrato[~df_extrato["used"]].copy()

        if candidatos.empty:
            return None

        # FILTRO 1: Valor exatamente igual (comparação em centavos via round)
        candidatos = candidatos[
            candidatos["valor_extrato"].round(2) == round(valor_razao, 2)
        ]

        if candidatos.empty:
            return None

        # FILTRO 2: Diferença de data dentro da tolerância
        if pd.notna(data_razao):
            diferenca_dias = (candidatos["data_extrato"] - data_razao).abs()
            candidatos = candidatos[
                diferenca_dias <= pd.Timedelta(days=self.TOLERANCIA_DIAS)
            ]

        if candidatos.empty:
            return None

        # Desempate: escolhe o candidato com menor diferença de data
        if pd.notna(data_razao):
            diferenca_dias = (candidatos["data_extrato"] - data_razao).abs()
            idx_melhor = diferenca_dias.idxmin()
        else:
            idx_melhor = candidatos.index[0]

        return idx_melhor, candidatos.loc[idx_melhor]

    # -------------------------------------------------------------------------
    # CRIAÇÃO DO REGISTRO DE MATCH
    # -------------------------------------------------------------------------
    def _criar_registro_match(
        self,
        idx_razao: int, row_razao: pd.Series,
        idx_extrato: int, row_extrato: pd.Series
    ) -> Dict:
        """
        Cria um dicionário com todos os dados do match encontrado.
        Este formato será usado pelo DataFrame final de resultados.
        """
        diferenca_dias = None
        if pd.notna(row_razao["data_razao"]) and pd.notna(row_extrato["data_extrato"]):
            diferenca_dias = abs((row_extrato["data_extrato"] - row_razao["data_razao"]).days)

        return {
            # ---- Dados do Razão ----
            "idx_razao": idx_razao,
            "data_razao": row_razao.get("data_razao"),
            "historico_razao": row_razao.get("historico", ""),
            "documento_razao": row_razao.get("documento", ""),
            "valor_razao": row_razao.get("valor_razao", 0.0),
            "conta_razao": row_razao.get("conta", ""),

            # ---- Dados do Extrato ----
            "idx_extrato": idx_extrato,
            "data_extrato": row_extrato.get("data_extrato"),
            "descricao_extrato": row_extrato.get("descricao", ""),
            "documento_extrato": row_extrato.get("documento", ""),
            "valor_extrato": row_extrato.get("valor_extrato", 0.0),

            # ---- Resultado do Match ----
            "status": "CONCILIADO",
            "confidence": 100.0,
            "tipo_match": "EXATO",
            "observacoes": f"Match exato | Δ dias: {diferenca_dias}",
            "diferenca_dias": diferenca_dias,
            "diferenca_valor": abs(
                abs(row_razao.get("valor_razao", 0.0)) -
                abs(row_extrato.get("valor_extrato", 0.0))
            ),
        }


# =============================================================================
# EXECUÇÃO DIRETA (teste isolado)
# =============================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    # Cria dados de teste simples
    df_razao = pd.DataFrame([
        {"data_razao": pd.Timestamp("2024-01-05"), "historico": "PIX JOAO",
         "documento": "TX001", "valor_razao": 500.00, "conta": "1.1.1.01", "used": False},
        {"data_razao": pd.Timestamp("2024-01-10"), "historico": "PAGAMENTO BOLETO",
         "documento": "BOL002", "valor_razao": 200.00, "conta": "1.1.1.01", "used": False},
    ])

    df_extrato = pd.DataFrame([
        {"data_extrato": pd.Timestamp("2024-01-05"), "descricao": "PIX RECEBIDO JOAO",
         "documento": "TX001", "valor_extrato": 500.00, "tipo": "C", "used": False},
        {"data_extrato": pd.Timestamp("2024-01-10"), "descricao": "BOLETO PAGO",
         "documento": "", "valor_extrato": 200.00, "tipo": "D", "used": False},
    ])

    engine = ExactMatch()
    df_razao_upd, df_extrato_upd, matches = engine.executar(df_razao, df_extrato)

    print(f"\n✅ Matches encontrados: {len(matches)}")
    for m in matches:
        print(f"  Razão: {m['historico_razao']} R${m['valor_razao']:.2f} "
              f"→ Extrato: {m['descricao_extrato']} | {m['status']} ({m['confidence']}%)")
