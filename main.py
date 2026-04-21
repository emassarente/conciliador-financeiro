# =============================================================================
# MAIN.PY - PONTO DE ENTRADA DO SISTEMA DE CONCILIAÇÃO FINANCEIRA
#
# Este arquivo coordena todo o sistema. Você pode:
#   1. Executar via linha de comando para processar arquivos diretamente
#   2. Usar como importação em outros scripts
#   3. Chamar o bot RPA + conciliação em sequência
#
# Uso via linha de comando:
#   python main.py --razao dados/razao.xlsx --extrato dados/extrato.xlsx
#   python main.py --razao dados/razao.xlsx --extrato dados/extrato.csv --conta 1.1.1.01
#   python main.py --demo    (roda com dados de demonstração)
# =============================================================================

import sys
import os
import argparse
import logging
from pathlib import Path
from datetime import datetime

# Garante que o diretório raiz está no path do Python
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from import_.razao_parser import RazaoParser
from import_.extrato_parser import ExtratoParser
from engine.conciliacao_engine import ConciliacaoEngine

# Configuração do sistema de logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(ROOT / "data" / "conciliacao.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)


# =============================================================================
# FUNÇÕES PRINCIPAIS
# =============================================================================

def executar_rpa(usuario: str, senha: str, conta: str,
                 data_ini: str, data_fim: str, empresa: str = "") -> str:
    """
    Executa o robô RPA para baixar o Razão do sistema Domínio.
    
    Args:
        usuario:   Login do usuário no Domínio
        senha:     Senha
        conta:     Número da conta contábil (ex: "1.1.1.01")
        data_ini:  Data inicial (DD/MM/AAAA)
        data_fim:  Data final (DD/MM/AAAA)
        empresa:   Código da empresa (opcional)
        
    Returns:
        Caminho do arquivo baixado
    """
    # Importação local para não falhar se o Playwright não estiver instalado
    from rpa.dominio_bot import DominioBot

    logger.info("🤖 Iniciando RPA - Download do Razão no Domínio...")

    bot = DominioBot(
        usuario=usuario,
        senha=senha,
        empresa=empresa,
        headless=False  # Mude para True para rodar em modo silencioso
    )

    arquivo = bot.executar(conta=conta, data_ini=data_ini, data_fim=data_fim)
    logger.info(f"✅ RPA concluído. Arquivo: {arquivo}")
    return arquivo


def executar_conciliacao(
    caminho_razao: str,
    caminho_extrato: str,
    conta_filtro: str = None,
    score_similaridade: float = 80.0,
    salvar_resultado: bool = True,
    pasta_saida: str = None
) -> "pd.DataFrame":
    """
    Executa o pipeline completo de conciliação:
    1. Lê e processa o Razão
    2. Lê e processa o Extrato
    3. Executa os 3 níveis de match
    4. Salva o resultado em Excel
    
    Args:
        caminho_razao:      Caminho do arquivo Excel/CSV do Razão
        caminho_extrato:    Caminho do arquivo Excel/CSV do Extrato
        conta_filtro:       Filtra por conta específica (opcional)
        score_similaridade: Score mínimo para match por similaridade
        salvar_resultado:   Se True, salva o resultado em Excel
        pasta_saida:        Pasta onde salvar o resultado
        
    Returns:
        DataFrame com o resultado completo da conciliação
    """
    import pandas as pd

    logger.info("=" * 60)
    logger.info("🚀 SISTEMA DE CONCILIAÇÃO FINANCEIRA")
    logger.info(f"   Razão:   {caminho_razao}")
    logger.info(f"   Extrato: {caminho_extrato}")
    logger.info("=" * 60)

    # ── ETAPA 1: LEITURA DO RAZÃO ──────────────────────────────────────────
    logger.info("\n📒 Etapa 1/3: Carregando Razão Contábil...")
    parser_razao = RazaoParser(conta_filtro=conta_filtro)
    df_razao = parser_razao.carregar(caminho_razao)

    if df_razao.empty:
        logger.error("❌ Nenhum lançamento encontrado no Razão. Verifique o arquivo.")
        return pd.DataFrame()

    # ── ETAPA 2: LEITURA DO EXTRATO ───────────────────────────────────────
    logger.info("\n🏦 Etapa 2/3: Carregando Extrato Bancário...")
    parser_extrato = ExtratoParser()
    df_extrato = parser_extrato.carregar(caminho_extrato)

    if df_extrato.empty:
        logger.error("❌ Nenhum lançamento encontrado no Extrato. Verifique o arquivo.")
        return pd.DataFrame()

    # ── ETAPA 3: CONCILIAÇÃO ──────────────────────────────────────────────
    logger.info("\n🔄 Etapa 3/3: Executando conciliação...")
    engine = ConciliacaoEngine(
        score_minimo_similaridade=score_similaridade,
        usar_similaridade=True
    )
    df_resultado = engine.conciliar(df_razao, df_extrato)

    # ── SALVAR RESULTADO ──────────────────────────────────────────────────
    if salvar_resultado and not df_resultado.empty:
        if pasta_saida is None:
            pasta_saida = str(ROOT / "data")
        os.makedirs(pasta_saida, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome_arquivo = f"conciliacao_{timestamp}.xlsx"
        caminho_saida = os.path.join(pasta_saida, nome_arquivo)

        df_resultado.to_excel(caminho_saida, index=False)
        logger.info(f"\n💾 Resultado salvo em: {caminho_saida}")

    return df_resultado


def executar_com_rpa(
    usuario: str, senha: str,
    conta: str, data_ini: str, data_fim: str,
    caminho_extrato: str,
    empresa: str = ""
):
    """
    Fluxo completo: RPA → Leitura → Conciliação.
    Baixa o Razão automaticamente e depois concilia com o extrato informado.
    """
    # Passo 1: Baixar o Razão via RPA
    caminho_razao = executar_rpa(
        usuario=usuario, senha=senha,
        conta=conta, data_ini=data_ini, data_fim=data_fim,
        empresa=empresa
    )

    # Passo 2: Conciliar
    df = executar_conciliacao(
        caminho_razao=caminho_razao,
        caminho_extrato=caminho_extrato,
        conta_filtro=conta
    )

    return df


# =============================================================================
# INTERFACE DE LINHA DE COMANDO (CLI)
# =============================================================================

def criar_argumentos():
    """Define os argumentos aceitos pela linha de comando."""
    parser = argparse.ArgumentParser(
        description="Sistema de Conciliação Financeira Automatizada",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos de uso:
  # Conciliação direta (com arquivos já baixados):
  python main.py --razao data/razao.xlsx --extrato data/extrato.xlsx

  # Filtrando por conta específica:
  python main.py --razao data/razao.xlsx --extrato data/extrato.xlsx --conta 1.1.1.01

  # Com o RPA do Domínio (baixa automaticamente):
  python main.py --rpa --usuario joao --senha 1234 \\
                 --conta 1.1.1.01 --data-ini 01/01/2024 --data-fim 31/01/2024 \\
                 --extrato data/extrato.xlsx

  # Modo demonstração (dados fictícios):
  python main.py --demo
        """
    )

    # Arquivos de entrada
    parser.add_argument("--razao", help="Caminho do arquivo do Razão Contábil (.xlsx ou .csv)")
    parser.add_argument("--extrato", help="Caminho do arquivo do Extrato Bancário (.xlsx ou .csv)")
    parser.add_argument("--conta", help="Filtrar por conta contábil específica (ex: 1.1.1.01)", default=None)

    # Opções de configuração
    parser.add_argument("--score", type=float, default=80.0,
                        help="Score mínimo para match por similaridade (padrão: 80)")

    # Modo RPA
    parser.add_argument("--rpa", action="store_true",
                        help="Usar RPA para baixar o Razão do Domínio automaticamente")
    parser.add_argument("--usuario", help="Login do usuário no Domínio (necessário para --rpa)")
    parser.add_argument("--senha", help="Senha do usuário no Domínio (necessário para --rpa)")
    parser.add_argument("--empresa", help="Código da empresa no Domínio", default="")
    parser.add_argument("--data-ini", help="Data inicial para o Razão (DD/MM/AAAA)", default=None)
    parser.add_argument("--data-fim", help="Data final para o Razão (DD/MM/AAAA)", default=None)

    # Modo demonstração
    parser.add_argument("--demo", action="store_true",
                        help="Executar com dados de demonstração")

    # Saída
    parser.add_argument("--saida", help="Pasta onde salvar o resultado Excel", default=None)

    return parser


def executar_demo():
    """Cria arquivos de exemplo e executa a conciliação com dados fictícios."""
    import pandas as pd
    from data.gerar_amostras import gerar_arquivos_exemplo

    logger.info("🧪 MODO DEMONSTRAÇÃO: Gerando dados fictícios...")
    caminhos = gerar_arquivos_exemplo()

    logger.info(f"   Razão:   {caminhos['razao']}")
    logger.info(f"   Extrato: {caminhos['extrato']}")

    df = executar_conciliacao(
        caminho_razao=caminhos["razao"],
        caminho_extrato=caminhos["extrato"],
    )

    if not df.empty:
        logger.info("\n📊 PRÉVIA DO RESULTADO:")
        print("\n" + df[["data_razao", "historico_razao", "valor_razao",
                          "status", "confidence"]].to_string(index=False))


# =============================================================================
# PONTO DE ENTRADA PRINCIPAL
# =============================================================================

if __name__ == "__main__":
    parser_cli = criar_argumentos()
    args = parser_cli.parse_args()

    # ── MODO DEMONSTRAÇÃO ─────────────────────────────────────────────────
    if args.demo:
        executar_demo()

    # ── MODO RPA ──────────────────────────────────────────────────────────
    elif args.rpa:
        if not all([args.usuario, args.senha, args.conta,
                    args.data_ini, args.data_fim, args.extrato]):
            parser_cli.error(
                "Para usar --rpa é necessário informar: "
                "--usuario, --senha, --conta, --data-ini, --data-fim, --extrato"
            )
        executar_com_rpa(
            usuario=args.usuario,
            senha=args.senha,
            conta=args.conta,
            data_ini=args.data_ini,
            data_fim=args.data_fim,
            caminho_extrato=args.extrato,
            empresa=args.empresa,
        )

    # ── MODO ARQUIVO DIRETO ───────────────────────────────────────────────
    elif args.razao and args.extrato:
        executar_conciliacao(
            caminho_razao=args.razao,
            caminho_extrato=args.extrato,
            conta_filtro=args.conta,
            score_similaridade=args.score,
            salvar_resultado=True,
            pasta_saida=args.saida,
        )

    # ── SEM ARGUMENTOS: mostra ajuda ─────────────────────────────────────
    else:
        print("\n" + "=" * 60)
        print("💰 SISTEMA DE CONCILIAÇÃO FINANCEIRA")
        print("=" * 60)
        print("\nPara usar via linha de comando, execute com --help:")
        print("  python main.py --help")
        print("\nPara abrir o dashboard visual (recomendado):")
        print("  streamlit run ui/dashboard.py")
        print("\nPara testar com dados de demonstração:")
        print("  python main.py --demo")
        print("=" * 60)
