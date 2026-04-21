# =============================================================================
# MOTOR DE CONCILIAÇÃO - MATCH COMBINADO (NÍVEL 2)
# Testa se a SOMA de até 3 lançamentos do Extrato corresponde
# a UM lançamento do Razão (ou vice-versa).
#
# Exemplo prático:
#   Razão:   1 lançamento de R$ 1.000,00
#   Extrato: 2 lançamentos de R$ 600,00 + R$ 400,00
#   → O robô percebe que 600 + 400 = 1000 e concilia os 3 juntos
#
# Resultado:
#   status      = MATCH_COMBINADO
#   confidence  = 85%
#   tipo_match  = COMBINADO
#   observacoes = Detalhe de quais itens foram combinados
# =============================================================================

import logging
import pandas as pd
from itertools import combinations
from typing import Tuple, List, Dict, Optional

logger = logging.getLogger(__name__)


class CombinationMatch:
    """
    Realiza o MATCH COMBINADO (Nível 2) da engine de conciliação.
    
    Como funciona:
    1. Para cada lançamento do Razão ainda não conciliado:
       - Busca no extrato grupos de 2 ou 3 itens cuja soma seja igual ao valor do Razão
       - Dentro de uma janela de datas de ± 3 dias
       - Soma deve ser exatamente igual (sem tolerância)
    
    2. Para evitar combinações infinitas (performance):
       - Máximo de 3 itens por combinação
       - Trabalha com no máximo 200 lançamentos por vez
       - Ordena candidatos por valor (heurística de poda)
    
    3. Após encontrar, marca TODOS os lançamentos envolvidos como used=True
    """

    TOLERANCIA_VALOR = 0.00    # Sem tolerância: a soma deve ser exatamente igual ao valor do Razão
    TOLERANCIA_DIAS = 3         # Diferença máxima de dias entre as datas
    MAX_ITENS_COMBO = 3         # Máximo de itens em uma combinação (4 → explosão combinatória)
    MAX_LANCAMENTOS = 60        # Limite de lançamentos para evitar explosão combinatória
    CONFIDENCE = 85.0           # Score de confiança padrão para este tipo de match

    def __init__(self):
        pass

    def executar(
        self,
        df_razao: pd.DataFrame,
        df_extrato: pd.DataFrame
    ) -> Tuple[pd.DataFrame, pd.DataFrame, List[Dict]]:
        """
        Executa o match combinado entre todos os lançamentos disponíveis.
        
        Args:
            df_razao:   DataFrame do Razão (já atualizado pelo ExactMatch)
            df_extrato: DataFrame do Extrato (já atualizado pelo ExactMatch)
            
        Returns:
            Tupla com:
            - df_razao atualizado
            - df_extrato atualizado
            - Lista de matches combinados encontrados
        """
        matches = []
        disponiveis_razao = len(df_razao[~df_razao["used"]])
        disponiveis_extrato = len(df_extrato[~df_extrato["used"]])
        logger.info(
            f"🔍 Iniciando Match Combinado | "
            f"Razão: {disponiveis_razao} | Extrato: {disponiveis_extrato} disponíveis"
        )

        # DIREÇÃO 1: 1 Razão → N Extrato
        for idx_razao, row_razao in df_razao[~df_razao["used"]].iterrows():
            resultado = self._buscar_combinacao_extrato(row_razao, df_extrato)

            if resultado is not None:
                indices_extrato = resultado
                df_razao.at[idx_razao, "used"] = True
                for idx_ext in indices_extrato:
                    df_extrato.at[idx_ext, "used"] = True
                match = self._criar_registro_match(
                    idx_razao, row_razao,
                    indices_extrato, df_extrato
                )
                matches.append(match)
                logger.debug(
                    f"✅ Match Combinado (1R→NE): Razão[{idx_razao}] R${row_razao['valor_razao']:.2f} "
                    f"← Extrato {indices_extrato}"
                )

        # DIREÇÃO 2: N Razão → 1 Extrato
        for idx_extrato, row_extrato in df_extrato[~df_extrato["used"]].iterrows():
            resultado = self._buscar_combinacao_razao(row_extrato, df_razao)

            if resultado is not None:
                indices_razao = resultado
                df_extrato.at[idx_extrato, "used"] = True
                for idx_r in indices_razao:
                    df_razao.at[idx_r, "used"] = True
                match = self._criar_registro_match_inverso(
                    indices_razao, df_razao,
                    idx_extrato, row_extrato
                )
                matches.append(match)
                logger.debug(
                    f"✅ Match Combinado (NR→1E): Extrato[{idx_extrato}] R${row_extrato['valor_extrato']:.2f} "
                    f"← Razão {indices_razao}"
                )

        logger.info(f"✅ Match Combinado concluído: {len(matches)} conciliações encontradas.")
        return df_razao, df_extrato, matches

    # -------------------------------------------------------------------------
    # BUSCA DE COMBINAÇÃO NO EXTRATO
    # -------------------------------------------------------------------------
    def _buscar_combinacao_razao(
        self,
        row_extrato: pd.Series,
        df_razao: pd.DataFrame
    ) -> Optional[List[int]]:
        """
        Direção inversa: para um lançamento do Extrato, busca N lançamentos
        do Razão cuja SOMA DE VALORES ABSOLUTOS corresponda ao valor do Extrato.
        """
        valor_alvo = abs(row_extrato["valor_extrato"])
        data_extrato = row_extrato["data_extrato"]

        candidatos = df_razao[~df_razao["used"]].copy()
        candidatos["_valor_abs"] = candidatos["valor_razao"].abs()

        if pd.notna(data_extrato):
            diferenca_dias = (candidatos["data_razao"] - data_extrato).abs()
            candidatos = candidatos[
                diferenca_dias <= pd.Timedelta(days=self.TOLERANCIA_DIAS)
            ]

        if len(candidatos) < 2:
            return None

        if len(candidatos) > self.MAX_LANCAMENTOS:
            candidatos["_diff_valor"] = (candidatos["_valor_abs"] - valor_alvo).abs()
            candidatos = candidatos.nsmallest(self.MAX_LANCAMENTOS, "_diff_valor")

        # Descarta itens com valor absoluto maior que o alvo
        candidatos = candidatos[candidatos["_valor_abs"] <= valor_alvo]

        if len(candidatos) < 2:
            return None

        indices = candidatos.index.tolist()
        valores = candidatos["_valor_abs"].tolist()

        for tamanho in range(2, self.MAX_ITENS_COMBO + 1):
            resultado = self._testar_combinacoes(indices, valores, valor_alvo, tamanho)
            if resultado:
                return resultado

        return None

    def _criar_registro_match_inverso(
        self,
        indices_razao: List[int],
        df_razao: pd.DataFrame,
        idx_extrato: int,
        row_extrato: pd.Series
    ) -> Dict:
        """
        Cria o registro do match N Razão → 1 Extrato.
        """
        linhas_razao = df_razao.loc[indices_razao]
        soma_razao = linhas_razao["valor_razao"].abs().sum()

        historicos = linhas_razao["historico"].tolist()
        datas_r    = linhas_razao["data_razao"].tolist()
        valores_r  = linhas_razao["valor_razao"].tolist()

        detalhes = []
        for i, (hist, dt, val) in enumerate(zip(historicos, datas_r, valores_r), 1):
            data_str = dt.strftime("%d/%m/%Y") if pd.notna(dt) else "?"
            detalhes.append(f"[{i}] {data_str} {hist} R${abs(val):.2f}")
        observacoes = "COMBINAÇÃO (N Razão→Extrato): " + " + ".join(detalhes)

        # Dado consolidado do Razão: usa a data/histórico do primeiro
        data_razao_cons   = datas_r[0] if datas_r else None
        hist_consolidado  = " | ".join(str(h) for h in historicos if h)
        conta_consolidada = " | ".join(
            str(linhas_razao.iloc[i].get("conta", "")) for i in range(len(linhas_razao))
        )

        return {
            "idx_razao":        str(indices_razao),
            "data_razao":       data_razao_cons,
            "historico_razao":  hist_consolidado,
            "documento_razao":  "",
            "valor_razao":      soma_razao,
            "conta_razao":      conta_consolidada,

            "idx_extrato":         idx_extrato,
            "data_extrato":        row_extrato.get("data_extrato"),
            "descricao_extrato":   row_extrato.get("descricao", ""),
            "documento_extrato":   row_extrato.get("documento", ""),
            "valor_extrato":       row_extrato.get("valor_extrato", 0.0),

            "status":              "MATCH_COMBINADO",
            "confidence":          self.CONFIDENCE,
            "tipo_match":          "COMBINADO",
            "observacoes":         observacoes,
            "diferenca_dias":      None,
            "diferenca_valor":     abs(soma_razao - abs(row_extrato.get("valor_extrato", 0.0))),
            "qtd_itens_combinados": len(indices_razao),
        }

    def _buscar_combinacao_extrato(
        self,
        row_razao: pd.Series,
        df_extrato: pd.DataFrame
    ) -> Optional[List[int]]:
        """
        Busca no extrato uma combinação de 2 ou 3 lançamentos cuja soma
        corresponda ao valor do lançamento do Razão.
        
        Returns:
            Lista de índices do extrato que formam a combinação, ou None
        """
        valor_alvo = abs(row_razao["valor_razao"])
        data_razao = row_razao["data_razao"]

        # Filtra candidatos: apenas não usados e dentro da janela de datas
        candidatos = df_extrato[~df_extrato["used"]].copy()

        if pd.notna(data_razao):
            diferenca_dias = (candidatos["data_extrato"] - data_razao).abs()
            candidatos = candidatos[
                diferenca_dias <= pd.Timedelta(days=self.TOLERANCIA_DIAS)
            ]

        if len(candidatos) < 2:
            return None  # Precisa de pelo menos 2 para combinar

        # Aplica limite de performance: máximo 200 lançamentos
        if len(candidatos) > self.MAX_LANCAMENTOS:
            # Heurística: ordena por proximidade de valor e pega os mais relevantes
            candidatos = candidatos.copy()
            candidatos["_diff_valor"] = (candidatos["valor_extrato"] - valor_alvo).abs()
            candidatos = candidatos.nsmallest(self.MAX_LANCAMENTOS, "_diff_valor")

        # Pré-filtro: descarta itens com valor maior que o alvo (evita combinações inúteis)
        candidatos = candidatos[candidatos["valor_extrato"] <= valor_alvo]

        if len(candidatos) < 2:
            return None

        indices = candidatos.index.tolist()
        valores = candidatos["valor_extrato"].tolist()

        # Testa combinações de 2 e depois 3 itens
        for tamanho in range(2, self.MAX_ITENS_COMBO + 1):
            resultado = self._testar_combinacoes(indices, valores, valor_alvo, tamanho)
            if resultado:
                return resultado

        return None

    def _testar_combinacoes(
        self,
        indices: list,
        valores: list,
        valor_alvo: float,
        tamanho: int
    ) -> Optional[List[int]]:
        """
        Testa todas as combinações de 'tamanho' elementos para encontrar
        aquela cuja soma se aproxima de 'valor_alvo'.
        
        Usa a heurística de poda: se o menor valor possível já ultrapassa
        o alvo, descarta a combinação.
        
        Returns:
            Lista de índices da combinação encontrada, ou None
        """
        pares = list(zip(indices, valores))
        # Ordena por valor para heurística de poda
        pares.sort(key=lambda x: x[1])
        indices_ord = [p[0] for p in pares]
        valores_ord = [p[1] for p in pares]

        for combo_idx in combinations(range(len(indices_ord)), tamanho):
            soma = sum(valores_ord[i] for i in combo_idx)
            soma_2 = round(float(soma), 2)
            alvo_2 = round(float(valor_alvo), 2)

            # Poda: se a soma já passa muito do alvo, e estamos ordenados,
            # combinações maiores só vão piorar
            if soma_2 > alvo_2:
                # Como está ordenado, se mesmo os menores já ultrapassam, para
                if combo_idx[0] == 0:
                    break
                continue

            # Verifica se a soma bate com o alvo dentro da tolerância
            if soma_2 == alvo_2:
                return [indices_ord[i] for i in combo_idx]

        return None

    # -------------------------------------------------------------------------
    # CRIAÇÃO DO REGISTRO DE MATCH
    # -------------------------------------------------------------------------
    def _criar_registro_match(
        self,
        idx_razao: int,
        row_razao: pd.Series,
        indices_extrato: List[int],
        df_extrato: pd.DataFrame
    ) -> Dict:
        """
        Cria o registro completo do match combinado para o DataFrame de resultados.
        
        Como são múltiplos lançamentos do extrato para um do razão,
        consolida as informações do extrato e detalha nas observações.
        """
        linhas_extrato = df_extrato.loc[indices_extrato]
        soma_extrato = linhas_extrato["valor_extrato"].sum()

        # Monta descrição consolidada do extrato (para exibir na tabela)
        descricoes = linhas_extrato["descricao"].tolist()
        datas = linhas_extrato["data_extrato"].tolist()
        valores = linhas_extrato["valor_extrato"].tolist()

        # Observações detalhadas (exibidas em amarelo no dashboard)
        detalhes = []
        for i, (desc, dt, val) in enumerate(zip(descricoes, datas, valores), 1):
            data_str = dt.strftime("%d/%m/%Y") if pd.notna(dt) else "?"
            detalhes.append(f"[{i}] {data_str} {desc} R${val:.2f}")
        observacoes = "COMBINAÇÃO: " + " + ".join(detalhes)

        # Data consolidada = data mais frequente (ou a primeira)
        data_consolidada = datas[0] if datas else None

        # Descrição consolidada
        descricao_consolidada = " | ".join(str(d) for d in descricoes if d)

        return {
            # ---- Dados do Razão ----
            "idx_razao": idx_razao,
            "data_razao": row_razao.get("data_razao"),
            "historico_razao": row_razao.get("historico", ""),
            "documento_razao": row_razao.get("documento", ""),
            "valor_razao": row_razao.get("valor_razao", 0.0),
            "conta_razao": row_razao.get("conta", ""),

            # ---- Dados do Extrato (consolidados) ----
            "idx_extrato": str(indices_extrato),   # Lista de índices como string
            "data_extrato": data_consolidada,
            "descricao_extrato": descricao_consolidada,
            "documento_extrato": "",
            "valor_extrato": soma_extrato,

            # ---- Resultado do Match ----
            "status": "MATCH_COMBINADO",
            "confidence": self.CONFIDENCE,
            "tipo_match": "COMBINADO",
            "observacoes": observacoes,
            "diferenca_dias": None,
            "diferenca_valor": abs(abs(row_razao.get("valor_razao", 0.0)) - soma_extrato),
            "qtd_itens_combinados": len(indices_extrato),
        }


# =============================================================================
# EXECUÇÃO DIRETA (teste isolado)
# =============================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    df_razao = pd.DataFrame([
        {"data_razao": pd.Timestamp("2024-01-05"), "historico": "TRANSFERENCIA TOTAL",
         "documento": "TX001", "valor_razao": 1000.00, "conta": "1.1.1.01", "used": False},
    ])

    df_extrato = pd.DataFrame([
        {"data_extrato": pd.Timestamp("2024-01-05"), "descricao": "PIX PARTE 1",
         "documento": "", "valor_extrato": 600.00, "tipo": "C", "used": False},
        {"data_extrato": pd.Timestamp("2024-01-06"), "descricao": "PIX PARTE 2",
         "documento": "", "valor_extrato": 400.00, "tipo": "C", "used": False},
    ])

    engine = CombinationMatch()
    df_r, df_e, matches = engine.executar(df_razao, df_extrato)

    print(f"\n✅ Matches Combinados: {len(matches)}")
    for m in matches:
        print(f"  Razão: R${m['valor_razao']:.2f} → {m['qtd_itens_combinados']} lançamentos extrato")
        print(f"  Obs: {m['observacoes']}")
