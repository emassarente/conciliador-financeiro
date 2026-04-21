# =============================================================================
# ORQUESTRADOR DA ENGINE DE CONCILIAÇÃO
# Coordena a execução dos 4 níveis de match em sequência:
#   0º → LearningMatch    (MATCH_APRENDIDO - ML)
#   1º → ExactMatch       (CONCILIADO - 100%)
#   2º → CombinationMatch  (MATCH_COMBINADO - 85%)
#   3º → SimilarityMatch   (MATCH_PROVAVEL - score%)
#   4º → Não conciliados   (NAO_CONCILIADO)
#
# Garante que cada lançamento seja usado no máximo uma vez.
# Gera o DataFrame final com todos os resultados consolidados.
# =============================================================================

import logging
import pandas as pd
from typing import Dict, List, Optional

from engine.exact_match import ExactMatch
from engine.combination_match import CombinationMatch
from engine.similarity_match import SimilarityMatch
from engine.learning_match import LearningMatch

logger = logging.getLogger(__name__)


class ConciliacaoEngine:
    """
    Orquestrador principal da conciliação financeira.
    
    Uso típico:
        engine = ConciliacaoEngine()
        df_resultado = engine.conciliar(df_razao, df_extrato)
    
    O DataFrame retornado contém uma linha por lançamento do Razão,
    com o status de conciliação e os dados do correspondente no extrato.
    """

    def __init__(
        self,
        score_minimo_similaridade: float = 80.0,
        usar_similaridade: bool = True,
        db_manager=None,
    ):
        """
        Args:
            score_minimo_similaridade: Score mínimo para match por similaridade (0-100)
            usar_similaridade: Se False, pula o nível de similaridade de texto
            db_manager: Instância de DatabaseManager para aprendizado ML (opcional)
        """
        self.score_minimo_similaridade = score_minimo_similaridade
        self.usar_similaridade = usar_similaridade
        self.db = db_manager

        # Instancia os 4 engines de match
        self.learning_match = LearningMatch(db_manager=db_manager)
        self.exact_match = ExactMatch()
        self.combination_match = CombinationMatch()
        self.similarity_match = SimilarityMatch(
            score_minimo=score_minimo_similaridade
        )

        # Treina o modelo se houver banco configurado
        if db_manager is not None:
            treinado = self.learning_match.treinar()
            if treinado:
                logger.info(
                    f"🧠 LearningMatch pronto: "
                    f"{self.learning_match.total_padroes} padrões aprendidos"
                )

    def conciliar(
        self,
        df_razao: pd.DataFrame,
        df_extrato: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Executa a conciliação completa entre o Razão e o Extrato.
        
        Fluxo:
        1. Match Aprendido (ML) → usa aprendizado de máquina para conciliar
        2. Match Exato       → concilia os óbvios
        3. Match Combinado   → testa somas de múltiplos lançamentos
        4. Match Similaridade → usa texto para os restantes
        5. Não Conciliados   → registra o que sobrou
        
        Args:
            df_razao:   DataFrame do Razão (saída do RazaoParser)
            df_extrato: DataFrame do Extrato (saída do ExtratoParser)
            
        Returns:
            DataFrame final com todas as colunas de resultado
        """
        logger.info("=" * 60)
        logger.info("🚀 INICIANDO CONCILIAÇÃO FINANCEIRA")
        logger.info(f"   Razão:   {len(df_razao)} lançamentos")
        logger.info(f"   Extrato: {len(df_extrato)} lançamentos")
        logger.info("=" * 60)

        # Garante que a coluna 'used' existe em ambos
        df_razao = df_razao.copy()
        df_extrato = df_extrato.copy()
        if "used" not in df_razao.columns:
            df_razao["used"] = False
        if "used" not in df_extrato.columns:
            df_extrato["used"] = False

        todos_matches: List[Dict] = []

        # ── NÍVEL 0: MATCH APRENDIDO (ML) ────────────────────────────────────────
        if self.learning_match.treinado:
            logger.info("\n🧠 NÍVEL 0: Match Aprendido (ML)")
            df_razao, df_extrato, matches_aprendidos = self.learning_match.executar(
                df_razao, df_extrato
            )
            todos_matches.extend(matches_aprendidos)
            self._log_progresso(df_razao, df_extrato, "Match Aprendido", len(matches_aprendidos))

        # ── NÍVEL 1: MATCH EXATO ─────────────────────────────────────────────────────────
        logger.info("\n📌 NÍVEL 1: Match Exato")
        df_razao, df_extrato, matches_exatos = self.exact_match.executar(
            df_razao, df_extrato
        )
        todos_matches.extend(matches_exatos)
        self._log_progresso(df_razao, df_extrato, "Match Exato", len(matches_exatos))

        # ── NÍVEL 2: MATCH COMBINADO ─────────────────────────────────────────
        logger.info("\n📌 NÍVEL 2: Match Combinado")
        df_razao, df_extrato, matches_combinados = self.combination_match.executar(
            df_razao, df_extrato
        )
        todos_matches.extend(matches_combinados)
        self._log_progresso(df_razao, df_extrato, "Match Combinado", len(matches_combinados))

        # ── NÍVEL 3: MATCH SIMILARIDADE ──────────────────────────────────────
        if self.usar_similaridade:
            logger.info("\n📌 NÍVEL 3: Match Similaridade")
            df_razao, df_extrato, matches_similares = self.similarity_match.executar(
                df_razao, df_extrato
            )
            todos_matches.extend(matches_similares)
            self._log_progresso(df_razao, df_extrato, "Match Similaridade", len(matches_similares))
        else:
            logger.info("\n⏭️  Match Similaridade desativado.")

        # ── NÍVEL 4: NÃO CONCILIADOS ─────────────────────────────────────────
        logger.info("\n📌 NÍVEL 4: Registrando Não Conciliados")
        nao_conciliados = self._registrar_nao_conciliados(df_razao, df_extrato)
        todos_matches.extend(nao_conciliados)

        # ── MONTA DATAFRAME FINAL ────────────────────────────────────────────
        df_resultado = self._montar_dataframe_final(todos_matches)

        # ── RELATÓRIO FINAL ──────────────────────────────────────────────────
        self._log_relatorio_final(df_resultado)

        return df_resultado

    # -------------------------------------------------------------------------
    # NÃO CONCILIADOS
    # -------------------------------------------------------------------------
    def _registrar_nao_conciliados(
        self,
        df_razao: pd.DataFrame,
        df_extrato: pd.DataFrame
    ) -> List[Dict]:
        """
        Registra todos os lançamentos que não encontraram par:
        - Lançamentos do Razão sem correspondente no Extrato
        - Lançamentos do Extrato sem correspondente no Razão
        (ambos aparecem como NAO_CONCILIADO)
        """
        nao_conciliados = []

        # Lançamentos do Razão sem par
        razao_sem_par = df_razao[~df_razao["used"]]
        for idx, row in razao_sem_par.iterrows():
            nao_conciliados.append({
                "idx_razao": idx,
                "data_razao": row.get("data_razao"),
                "historico_razao": row.get("historico", ""),
                "documento_razao": row.get("documento", ""),
                "valor_razao": row.get("valor_razao", 0.0),
                "conta_razao": row.get("conta", ""),

                "idx_extrato": None,
                "data_extrato": None,
                "descricao_extrato": "",
                "documento_extrato": "",
                "valor_extrato": None,

                "status": "NAO_CONCILIADO",
                "confidence": 0.0,
                "tipo_match": "NAO_CONCILIADO",
                "observacoes": "Sem correspondente no extrato bancário",
                "diferenca_dias": None,
                "diferenca_valor": None,
                "origem": "RAZAO",
            })

        # Lançamentos do Extrato sem par (aparecem separados no dashboard)
        extrato_sem_par = df_extrato[~df_extrato["used"]]
        for idx, row in extrato_sem_par.iterrows():
            nao_conciliados.append({
                "idx_razao": None,
                "data_razao": None,
                "historico_razao": "",
                "documento_razao": "",
                "valor_razao": None,
                "conta_razao": "",

                "idx_extrato": idx,
                "data_extrato": row.get("data_extrato"),
                "descricao_extrato": row.get("descricao", ""),
                "documento_extrato": row.get("documento", ""),
                "valor_extrato": row.get("valor_extrato", 0.0),

                "status": "NAO_CONCILIADO",
                "confidence": 0.0,
                "tipo_match": "NAO_CONCILIADO",
                "observacoes": "Sem correspondente no razão contábil",
                "diferenca_dias": None,
                "diferenca_valor": None,
                "origem": "EXTRATO",
            })

        logger.info(
            f"   Razão sem par: {len(razao_sem_par)} | "
            f"Extrato sem par: {len(extrato_sem_par)}"
        )
        return nao_conciliados

    # -------------------------------------------------------------------------
    # DATAFRAME FINAL
    # -------------------------------------------------------------------------
    def _montar_dataframe_final(self, todos_matches: List[Dict]) -> pd.DataFrame:
        """
        Monta o DataFrame final a partir da lista de todos os matches.
        Define a ordem das colunas e os tipos de dados corretos.
        """
        if not todos_matches:
            logger.warning("⚠️ Nenhum resultado de conciliação gerado.")
            return pd.DataFrame()

        df = pd.DataFrame(todos_matches)

        # Ordem das colunas para exibição no dashboard
        ordem_colunas = [
            # Dados do Razão
            "data_razao",
            "historico_razao",
            "documento_razao",
            "valor_razao",
            "conta_razao",
            # Dados do Extrato
            "data_extrato",
            "descricao_extrato",
            "documento_extrato",
            "valor_extrato",
            # Resultado
            "status",
            "tipo_match",
            "confidence",
            "observacoes",
            # Auxiliares
            "diferenca_dias",
            "diferenca_valor",
            "origem",
        ]

        # Adiciona colunas que podem ter sido criadas por módulos específicos
        colunas_extras = [c for c in df.columns if c not in ordem_colunas
                          and not c.startswith("idx")]
        colunas_finais = [c for c in ordem_colunas if c in df.columns] + colunas_extras

        df = df[colunas_finais].copy()

        # Garante tipos corretos
        for col in ["data_razao", "data_extrato"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")

        for col in ["valor_razao", "valor_extrato", "confidence"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Ordena por status (conciliados primeiro) e depois por data
        ordem_status = {
            "MATCH_APRENDIDO": 0,
            "CONCILIADO": 1,
            "MATCH_COMBINADO": 2,
            "MATCH_PROVAVEL": 3,
            "NAO_CONCILIADO": 4,
        }
        df["_ordem"] = df["status"].map(ordem_status).fillna(9)
        df.sort_values(["_ordem", "data_razao"], inplace=True)
        df.drop(columns=["_ordem"], inplace=True)
        df.reset_index(drop=True, inplace=True)

        return df

    # -------------------------------------------------------------------------
    # UTILITÁRIOS DE LOG
    # -------------------------------------------------------------------------
    def _log_progresso(
        self,
        df_razao: pd.DataFrame,
        df_extrato: pd.DataFrame,
        etapa: str,
        encontrados: int
    ):
        """Registra o progresso após cada nível de match."""
        restante_razao = len(df_razao[~df_razao["used"]])
        restante_extrato = len(df_extrato[~df_extrato["used"]])
        logger.info(
            f"   {etapa}: {encontrados} matches | "
            f"Restantes → Razão: {restante_razao} | Extrato: {restante_extrato}"
        )

    def _log_relatorio_final(self, df: pd.DataFrame):
        """Exibe o relatório final com as métricas de conciliação."""
        logger.info("\n" + "=" * 60)
        logger.info("📊 RELATÓRIO FINAL DE CONCILIAÇÃO")
        logger.info("=" * 60)

        total = len(df)
        if total == 0:
            logger.info("Nenhum resultado.")
            return

        for status in ["MATCH_APRENDIDO", "CONCILIADO", "MATCH_COMBINADO",
                        "MATCH_PROVAVEL", "NAO_CONCILIADO"]:
            qtd = len(df[df["status"] == status])
            pct = (qtd / total * 100) if total > 0 else 0
            icone = {
                "MATCH_APRENDIDO": "🧠",
                "CONCILIADO": "✅",
                "MATCH_COMBINADO": "🟡",
                "MATCH_PROVAVEL": "🔵",
                "NAO_CONCILIADO": "🔴",
            }.get(status, "")
            logger.info(f"  {icone} {status:<20}: {qtd:>4} ({pct:.1f}%)")

        logger.info(f"\n  Total de registros: {total}")
        logger.info("=" * 60)

    # -------------------------------------------------------------------------
    # MÉTODOS AUXILIARES PARA ANÁLISE
    # -------------------------------------------------------------------------
    def obter_metricas(self, df_resultado: pd.DataFrame) -> Dict:
        """
        Retorna dicionário com as métricas da conciliação.
        Usado pelo dashboard para exibir os KPIs.
        """
        if df_resultado.empty:
            return {
                "total": 0, "conciliados": 0, "combinados": 0,
                "provaveis": 0, "nao_conciliados": 0,
                "pct_conciliacao": 0.0,
            }

        total       = len(df_resultado)
        aprendidos  = len(df_resultado[df_resultado["status"] == "MATCH_APRENDIDO"])
        conciliados = len(df_resultado[df_resultado["status"] == "CONCILIADO"])
        combinados  = len(df_resultado[df_resultado["status"] == "MATCH_COMBINADO"])
        provaveis   = len(df_resultado[df_resultado["status"] == "MATCH_PROVAVEL"])
        manuais     = len(df_resultado[df_resultado["status"] == "MANUAL_CONCILIADO"])
        nao_conc    = len(df_resultado[df_resultado["status"] == "NAO_CONCILIADO"])

        total_conciliaveis = total - nao_conc
        pct = (total_conciliaveis / total * 100) if total > 0 else 0

        return {
            "total":            total,
            "aprendidos":       aprendidos,
            "conciliados":      conciliados,
            "combinados":       combinados,
            "provaveis":        provaveis,
            "manuais":          manuais,
            "nao_conciliados":  nao_conc,
            "pct_conciliacao":  round(pct, 1),
        }
