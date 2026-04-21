# =============================================================================
# MOTOR DE CONCILIAÇÃO - MATCH POR APRENDIZADO (NÍVEL 0)
# Usa TF-IDF + Logistic Regression treinado com histórico de pares confirmados.
#
# Fluxo:
#   1. Carrega padrões do banco (pares razão↔extrato já confirmados)
#   2. Treina um classificador: dado "historico_razao" → prediz "descricao_extrato"
#   3. Para cada lançamento do Razão ainda não conciliado:
#      - Vetoriza o histórico com TF-IDF
#      - Prediz a descrição do extrato mais provável
#      - Busca no extrato atual o lançamento mais similar à predição
#      - Se valor também bate (dentro de tolerância) → MATCH_APRENDIDO
#
# Requisito: scikit-learn >= 1.0
# Mínimo de pares para treinar: MIN_AMOSTRAS (padrão 5)
# =============================================================================

import logging
import re
import unicodedata
import pandas as pd
from typing import Tuple, List, Dict, Optional

logger = logging.getLogger(__name__)

MIN_AMOSTRAS    = 5      # mínimo de padrões para treinar o modelo
CONFIDENCE      = 92.0   # score de confiança atribuído ao match aprendido
TOLERANCIA_DIAS = 5      # janela de datas (dias)
TOLERANCIA_VALOR = 0.01  # tolerância de valor (R$)
SIM_THRESHOLD   = 0.55   # similaridade mínima TF-IDF para aceitar predição


def _normalizar(texto: str) -> str:
    """Remove acentos, passa para maiúsculas, colapsa espaços."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.upper()
    t = re.sub(r"[^A-Z0-9 ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


class LearningMatch:
    """
    Realiza o MATCH POR APRENDIZADO (Nível 0) da engine de conciliação.

    É executado ANTES dos outros níveis. Se houver histórico suficiente,
    tenta predizer o par correto antes de qualquer heurística.
    """

    def __init__(self, db_manager=None):
        self.db    = db_manager
        self._modelo         = None
        self._vectorizer     = None
        self._labels_extrato = None   # lista de descrições conhecidas do extrato
        self._treinado       = False
        self._total_padroes  = 0

    # ─────────────────────────────────────────────────────────────────────────
    # TREINAMENTO
    # ─────────────────────────────────────────────────────────────────────────

    def treinar(self) -> bool:
        """
        Carrega padrões do banco e treina o modelo TF-IDF + LogisticRegression.
        Retorna True se o modelo foi treinado com sucesso, False caso contrário.
        """
        if self.db is None:
            logger.warning("🧠 LearningMatch: nenhum banco configurado.")
            return False

        try:
            from sklearn.pipeline import Pipeline
            from sklearn.linear_model import LogisticRegression
            from sklearn.feature_extraction.text import TfidfVectorizer
        except ImportError:
            logger.warning("🧠 scikit-learn não instalado — LearningMatch desativado.")
            return False

        df_padroes = self.db.obter_padroes(min_frequencia=1)
        self._total_padroes = len(df_padroes)

        if len(df_padroes) < MIN_AMOSTRAS:
            logger.info(
                f"🧠 LearningMatch: apenas {len(df_padroes)} padrões "
                f"(mínimo {MIN_AMOSTRAS}) — aguardando mais histórico."
            )
            return False

        # Pondera cada amostra pela frequência (mais frequente = mais peso)
        X, y, pesos = [], [], []
        for _, row in df_padroes.iterrows():
            hist = _normalizar(row["historico_razao"])
            desc = _normalizar(row["descricao_extrato"])
            freq = int(row["frequencia"])
            X.append(hist)
            y.append(desc)
            pesos.append(freq)

        self._pipeline = Pipeline([
            ("tfidf", TfidfVectorizer(
                analyzer="char_wb",     # n-gramas de caracteres — robustez a abreviações
                ngram_range=(2, 4),
                max_features=5000,
                sublinear_tf=True,
            )),
            ("clf", LogisticRegression(
                max_iter=1000,
                C=5.0,
                solver="lbfgs",
                multi_class="auto",
            )),
        ])

        self._pipeline.fit(X, y, clf__sample_weight=pesos)
        self._labels_extrato = list(set(y))
        self._treinado = True

        logger.info(
            f"🧠 LearningMatch treinado: {len(df_padroes)} padrões | "
            f"{len(self._labels_extrato)} classes únicas."
        )
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # PREDIÇÃO
    # ─────────────────────────────────────────────────────────────────────────

    def _predizer(self, historico: str) -> Tuple[Optional[str], float]:
        """
        Para um histórico do Razão, prediz a descrição do Extrato e retorna
        (descricao_predita, probabilidade).
        """
        if not self._treinado:
            return None, 0.0
        hist_norm = _normalizar(historico)
        proba = self._pipeline.predict_proba([hist_norm])[0]
        classes = self._pipeline.classes_
        idx_melhor = proba.argmax()
        return classes[idx_melhor], float(proba[idx_melhor])

    # ─────────────────────────────────────────────────────────────────────────
    # EXECUÇÃO
    # ─────────────────────────────────────────────────────────────────────────

    def executar(
        self,
        df_razao: pd.DataFrame,
        df_extrato: pd.DataFrame
    ) -> Tuple[pd.DataFrame, pd.DataFrame, List[Dict]]:
        """
        Executa o match por aprendizado.

        Returns:
            Tupla (df_razao, df_extrato, lista_de_matches)
        """
        matches = []

        if not self._treinado:
            logger.info("🧠 LearningMatch: modelo não treinado — pulando.")
            return df_razao, df_extrato, matches

        disponiveis = len(df_razao[~df_razao["used"]])
        logger.info(
            f"🧠 Iniciando LearningMatch | "
            f"Razão: {disponiveis} disponíveis | "
            f"Padrões: {self._total_padroes}"
        )

        for idx_razao, row_razao in df_razao[~df_razao["used"]].iterrows():
            historico = str(row_razao.get("historico", "") or "")
            if not historico:
                continue

            desc_predita, prob = self._predizer(historico)
            if prob < SIM_THRESHOLD:
                continue

            # Busca no extrato o lançamento mais similar à predição
            resultado = self._buscar_no_extrato(
                desc_predita, row_razao, df_extrato
            )
            if resultado is None:
                continue

            idx_extrato, row_extrato, sim = resultado

            # Marca como usados
            df_razao.at[idx_razao, "used"]   = True
            df_extrato.at[idx_extrato, "used"] = True

            match = self._criar_registro(
                idx_razao, row_razao,
                idx_extrato, row_extrato,
                prob, sim
            )
            matches.append(match)
            logger.debug(
                f"🧠 APRENDIDO: '{historico[:40]}' → '{row_extrato.get('descricao','')[:40]}' "
                f"(prob={prob:.0%}, sim={sim:.0%})"
            )

        logger.info(f"🧠 LearningMatch concluído: {len(matches)} matches aprendidos.")
        return df_razao, df_extrato, matches

    def _buscar_no_extrato(
        self,
        desc_predita: str,
        row_razao: pd.Series,
        df_extrato: pd.DataFrame
    ) -> Optional[Tuple[int, pd.Series, float]]:
        """
        Busca no extrato o lançamento que melhor combina com a predição,
        considerando: similaridade textual + valor + janela de datas.
        """
        from rapidfuzz import fuzz

        valor_razao = abs(row_razao.get("valor_razao", 0))
        data_razao  = row_razao.get("data_razao")

        candidatos = df_extrato[~df_extrato["used"]].copy()

        # Filtro de data
        if pd.notna(data_razao):
            diff = (candidatos["data_extrato"] - data_razao).abs()
            candidatos = candidatos[diff <= pd.Timedelta(days=TOLERANCIA_DIAS)]

        # Filtro de valor
        if valor_razao > 0:
            candidatos = candidatos[
                (candidatos["valor_extrato"] - valor_razao).abs() <= TOLERANCIA_VALOR
            ]

        if candidatos.empty:
            return None

        # Escolhe por similaridade textual com a predição
        melhor_idx  = None
        melhor_sim  = 0.0
        melhor_row  = None

        for idx, row in candidatos.iterrows():
            desc = _normalizar(str(row.get("descricao", "") or ""))
            sim  = fuzz.token_set_ratio(desc_predita, desc) / 100.0
            if sim > melhor_sim:
                melhor_sim  = sim
                melhor_idx  = idx
                melhor_row  = row

        if melhor_idx is None or melhor_sim < 0.40:
            return None

        return melhor_idx, melhor_row, melhor_sim

    def _criar_registro(
        self,
        idx_razao: int,
        row_razao: pd.Series,
        idx_extrato: int,
        row_extrato: pd.Series,
        prob: float,
        sim: float
    ) -> Dict:
        data_r = row_razao.get("data_razao")
        data_e = row_extrato.get("data_extrato")
        delta  = None
        if pd.notna(data_r) and pd.notna(data_e):
            delta = abs((data_e - data_r).days)

        hist = str(row_razao.get("historico", "") or "")
        desc = str(row_extrato.get("descricao", "") or "")

        # ── Confidence final = 70% empresa + 30% global
        empresa_score = prob          # 0.0–1.0  (modelo treinado com padrões da empresa)
        global_score  = 0.0
        if self.db is not None:
            try:
                global_score = self.db.score_global(hist, desc)   # 0.0–1.0
            except Exception:
                pass
        confidence_final = round((empresa_score * 0.70 + global_score * 0.30) * 100, 1)

        return {
            "idx_razao":         idx_razao,
            "data_razao":        data_r,
            "historico_razao":   hist,
            "documento_razao":   row_razao.get("documento", ""),
            "valor_razao":       row_razao.get("valor_razao", 0.0),
            "conta_razao":       row_razao.get("conta", ""),

            "idx_extrato":       idx_extrato,
            "data_extrato":      data_e,
            "descricao_extrato": desc,
            "documento_extrato": row_extrato.get("documento", ""),
            "valor_extrato":     row_extrato.get("valor_extrato", 0.0),

            "status":            "MATCH_APRENDIDO",
            "confidence":        confidence_final,
            "tipo_match":        "APRENDIDO",
            "observacoes":       (
                f"🧠 Modelo ML | Empresa: {empresa_score:.0%} | "
                f"Global: {global_score:.0%} | "
                f"Sim texto: {sim:.0%} | "
                f"Padrões: {self._total_padroes}"
            ),
            "diferenca_dias":    delta,
            "diferenca_valor":   abs(
                abs(row_razao.get("valor_razao", 0.0)) -
                abs(row_extrato.get("valor_extrato", 0.0))
            ),
            "qtd_itens_combinados": 1,
        }

    @property
    def treinado(self) -> bool:
        return self._treinado

    @property
    def total_padroes(self) -> int:
        return self._total_padroes
