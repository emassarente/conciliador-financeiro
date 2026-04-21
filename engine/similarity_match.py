# =============================================================================
# MOTOR DE CONCILIAÇÃO - MATCH POR SIMILARIDADE (NÍVEL 3)
# Compara a descrição/histórico do Razão com a descrição do Extrato
# usando algoritmos de similaridade de texto (fuzzy matching).
#
# Exemplo prático:
#   Razão:   "PIX JOAO SILVA"
#   Extrato: "PIX J SILVA"
#   → Similaridade 87% → MATCH_PROVAVEL
#
# Tecnologia: rapidfuzz (muito mais rápido que fuzzywuzzy)
#
# Resultado:
#   status      = MATCH_PROVAVEL
#   confidence  = Score de similaridade (0-100%)
#   tipo_match  = SIMILARIDADE
#   observacoes = Detalhes do que foi comparado e o score obtido
# =============================================================================

import logging
import pandas as pd
from typing import Tuple, List, Dict, Optional

try:
    from rapidfuzz import fuzz, process
    RAPIDFUZZ_DISPONIVEL = True
except ImportError:
    RAPIDFUZZ_DISPONIVEL = False
    logging.warning(
        "⚠️ rapidfuzz não instalado. Similarity match será desativado. "
        "Execute: pip install rapidfuzz"
    )

logger = logging.getLogger(__name__)


class SimilarityMatch:
    """
    Realiza o MATCH POR SIMILARIDADE DE TEXTO (Nível 3) da engine de conciliação.
    
    Como funciona:
    1. Para cada lançamento do Razão ainda não conciliado:
       - Compara o histórico (texto) com a descrição de cada lançamento do extrato
       - Usa múltiplos algoritmos fuzzy para calcular similaridade:
         * token_set_ratio: ignora ordem das palavras ("JOAO SILVA" ~ "SILVA JOAO")
         * partial_ratio: detecta substring ("PIX J SILVA" em "PIX JOAO SILVA")
         * ratio: similaridade geral da string
       - Usa o maior score entre os três
    
    2. Aplica o score mínimo de 80% para considerar como match
    
    3. Também considera a diferença de valor como critério de desempate
       (máximo de 10% de diferença de valor para ser considerado)
    
    Importante: Este nível só roda APÓS os matchs exato e combinado.
    """

    SCORE_MINIMO = 80.0         # Score mínimo de similaridade para aceitar o match
    TOLERANCIA_VALOR_PCT = 0.10  # 10% de diferença de valor permitida
    TOLERANCIA_DIAS = 7          # Janela de datas mais larga que o exact match
    CONFIDENCE_BASE = 0.0        # Base de confiança: será o próprio score

    def __init__(self, score_minimo: float = None):
        """
        Args:
            score_minimo: Score mínimo para aceitar um match (padrão: 80.0)
        """
        if score_minimo is not None:
            self.SCORE_MINIMO = score_minimo

        if not RAPIDFUZZ_DISPONIVEL:
            logger.warning("⚠️ SimilarityMatch desativado: rapidfuzz não disponível.")

    def executar(
        self,
        df_razao: pd.DataFrame,
        df_extrato: pd.DataFrame
    ) -> Tuple[pd.DataFrame, pd.DataFrame, List[Dict]]:
        """
        Executa o match por similaridade entre todos os lançamentos disponíveis.
        
        Args:
            df_razao:   DataFrame do Razão (atualizado pelos matchs anteriores)
            df_extrato: DataFrame do Extrato (atualizado pelos matchs anteriores)
            
        Returns:
            Tupla com:
            - df_razao atualizado
            - df_extrato atualizado
            - Lista de matches por similaridade encontrados
        """
        matches = []

        if not RAPIDFUZZ_DISPONIVEL:
            logger.warning("⚠️ Similarity Match pulado: rapidfuzz não instalado.")
            return df_razao, df_extrato, matches

        disponiveis_razao = len(df_razao[~df_razao["used"]])
        disponiveis_extrato = len(df_extrato[~df_extrato["used"]])
        logger.info(
            f"🔍 Iniciando Match Similaridade | "
            f"Razão: {disponiveis_razao} | Extrato: {disponiveis_extrato} disponíveis"
        )

        df_razao_ord = df_razao[~df_razao["used"]].sort_values("data_razao", ascending=True)
        for idx_razao, row_razao in df_razao_ord.iterrows():

            resultado = self._buscar_por_similaridade(row_razao, df_extrato)

            if resultado is not None:
                idx_extrato, row_extrato, score = resultado

                df_razao.at[idx_razao, "used"] = True
                df_extrato.at[idx_extrato, "used"] = True

                match = self._criar_registro_match(
                    idx_razao, row_razao,
                    idx_extrato, row_extrato,
                    score
                )
                matches.append(match)
                logger.debug(
                    f"✅ Match Similaridade: '{row_razao.get('historico', '')}' "
                    f"~ '{row_extrato.get('descricao', '')}' | Score: {score:.1f}%"
                )

        logger.info(f"✅ Match Similaridade concluído: {len(matches)} conciliações encontradas.")
        return df_razao, df_extrato, matches

    # -------------------------------------------------------------------------
    # BUSCA POR SIMILARIDADE NO EXTRATO
    # -------------------------------------------------------------------------
    def _buscar_por_similaridade(
        self,
        row_razao: pd.Series,
        df_extrato: pd.DataFrame
    ) -> Optional[Tuple[int, pd.Series, float]]:
        """
        Para um lançamento do Razão, busca o melhor candidato no extrato
        usando similaridade de texto combinada com filtro de valor e data.
        
        Returns:
            Tupla (índice, linha, score) do melhor candidato, ou None
        """
        texto_razao = row_razao.get("historico_norm", row_razao.get("historico", ""))
        valor_razao = abs(row_razao.get("valor_razao", 0.0))
        data_razao = row_razao.get("data_razao")

        if not texto_razao or len(texto_razao) < 3:
            return None  # Texto muito curto para comparar

        # Filtra candidatos: apenas não usados
        candidatos = df_extrato[~df_extrato["used"]].copy()

        if candidatos.empty:
            return None

        # Filtro de data: janela de ± 7 dias
        if pd.notna(data_razao):
            diferenca_dias = (candidatos["data_extrato"] - data_razao).abs()
            candidatos = candidatos[
                diferenca_dias <= pd.Timedelta(days=self.TOLERANCIA_DIAS)
            ]

        if candidatos.empty:
            return None

        # Filtro de valor: tolerância de 10%
        if valor_razao > 0:
            min_val = valor_razao * (1 - self.TOLERANCIA_VALOR_PCT)
            max_val = valor_razao * (1 + self.TOLERANCIA_VALOR_PCT)
            candidatos = candidatos[
                (candidatos["valor_extrato"] >= min_val) &
                (candidatos["valor_extrato"] <= max_val)
            ]

        if candidatos.empty:
            return None

        # Calcula score de similaridade para cada candidato
        melhor_idx = None
        melhor_score = 0.0
        melhor_row = None

        for idx, row_ext in candidatos.iterrows():
            texto_extrato = row_ext.get("descricao_norm", row_ext.get("descricao", ""))
            if not texto_extrato or len(texto_extrato) < 3:
                continue

            score = self._calcular_similaridade(texto_razao, texto_extrato)

            if score > melhor_score:
                melhor_score = score
                melhor_idx = idx
                melhor_row = row_ext

        # Retorna apenas se o score atingiu o mínimo
        if melhor_score >= self.SCORE_MINIMO and melhor_idx is not None:
            return melhor_idx, melhor_row, melhor_score

        return None

    def _calcular_similaridade(self, texto1: str, texto2: str) -> float:
        """
        Calcula a similaridade entre dois textos usando múltiplos algoritmos
        e retorna o MAIOR score entre eles.
        
        Algoritmos usados:
        - token_set_ratio: melhor para textos com mesmas palavras em ordens diferentes
        - partial_ratio: melhor para quando um texto é subconjunto do outro
        - ratio: similaridade geral da string
        
        Retorna:
            Score de 0 a 100
        """
        t1 = str(texto1).strip()
        t2 = str(texto2).strip()

        score_token = fuzz.token_set_ratio(t1, t2)
        score_partial = fuzz.partial_ratio(t1, t2)
        score_ratio = fuzz.ratio(t1, t2)

        # Retorna o maior score (estratégia otimista)
        return max(score_token, score_partial, score_ratio)

    # -------------------------------------------------------------------------
    # CRIAÇÃO DO REGISTRO DE MATCH
    # -------------------------------------------------------------------------
    def _criar_registro_match(
        self,
        idx_razao: int, row_razao: pd.Series,
        idx_extrato: int, row_extrato: pd.Series,
        score: float
    ) -> Dict:
        """
        Cria o registro completo do match por similaridade.
        O campo 'observacoes' detalha o que foi comparado e o score.
        """
        texto_razao = row_razao.get("historico", "")
        texto_extrato = row_extrato.get("descricao", "")

        diferenca_dias = None
        if pd.notna(row_razao.get("data_razao")) and pd.notna(row_extrato.get("data_extrato")):
            diferenca_dias = abs(
                (row_extrato["data_extrato"] - row_razao["data_razao"]).days
            )

        observacoes = (
            f"SIMILARIDADE {score:.1f}% | "
            f"Razão: '{texto_razao}' → Extrato: '{texto_extrato}'"
        )

        return {
            # ---- Dados do Razão ----
            "idx_razao": idx_razao,
            "data_razao": row_razao.get("data_razao"),
            "historico_razao": texto_razao,
            "documento_razao": row_razao.get("documento", ""),
            "valor_razao": row_razao.get("valor_razao", 0.0),
            "conta_razao": row_razao.get("conta", ""),

            # ---- Dados do Extrato ----
            "idx_extrato": idx_extrato,
            "data_extrato": row_extrato.get("data_extrato"),
            "descricao_extrato": texto_extrato,
            "documento_extrato": row_extrato.get("documento", ""),
            "valor_extrato": row_extrato.get("valor_extrato", 0.0),

            # ---- Resultado do Match ----
            "status": "MATCH_PROVAVEL",
            "confidence": round(score, 1),
            "tipo_match": "SIMILARIDADE",
            "observacoes": observacoes,
            "score_similaridade": round(score, 1),
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

    df_razao = pd.DataFrame([
        {"data_razao": pd.Timestamp("2024-01-05"), "historico": "PIX JOAO SILVA",
         "historico_norm": "PIX JOAO SILVA",
         "documento": "", "valor_razao": 500.00, "conta": "1.1.1.01", "used": False},
        {"data_razao": pd.Timestamp("2024-01-10"), "historico": "PAGAMENTO FORNECEDOR ABC",
         "historico_norm": "PAGAMENTO FORNECEDOR ABC",
         "documento": "", "valor_razao": 300.00, "conta": "1.1.1.01", "used": False},
    ])

    df_extrato = pd.DataFrame([
        {"data_extrato": pd.Timestamp("2024-01-05"), "descricao": "PIX J SILVA",
         "descricao_norm": "PIX J SILVA",
         "documento": "", "valor_extrato": 500.00, "tipo": "C", "used": False},
        {"data_extrato": pd.Timestamp("2024-01-10"), "descricao": "PGTO FORNEC ABC",
         "descricao_norm": "PGTO FORNEC ABC",
         "documento": "", "valor_extrato": 300.00, "tipo": "D", "used": False},
    ])

    engine = SimilarityMatch(score_minimo=75.0)
    df_r, df_e, matches = engine.executar(df_razao, df_extrato)

    print(f"\n✅ Matches por Similaridade: {len(matches)}")
    for m in matches:
        print(f"  Score: {m['confidence']}% | {m['observacoes']}")
