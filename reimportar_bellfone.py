"""
Script de reimportação da Bellfone com o parser corrigido.
Segue o mesmo fluxo do dashboard: parse → engine → salva no banco.
"""
import sys, warnings, os
import pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))

from import_.razao_parser import RazaoParser
from import_.extrato_parser import ExtratoParser
from database.db_manager import DatabaseManager
from engine.conciliacao_engine import ConciliacaoEngine

CLIENTE_ID  = 2
PDF_RAZAO   = "/Users/eduardomassarente/Bellfone/Razão - BANCO DO BRASILAG 1820-1 CC 456307-7 01.2026.pdf"
XLS_EXTRATO = "/Users/eduardomassarente/Bellfone/extrato banco do brasil.xls"

db = DatabaseManager()

# 1. Limpar dados antigos
r = db.limpar_dados_cliente(cliente_id=CLIENTE_ID)
print(f"🗑️  Limpeza: {r}")

# 2. Parse Razão (igual ao dashboard — df com colunas valor_razao, historico_razao, etc.)
print("📄 Lendo Razão PDF...")
p = RazaoParser()
df_razao = p.carregar(PDF_RAZAO)
meta = p.obter_metadados()
hist_col = "historico_razao" if "historico_razao" in df_razao.columns else "historico"
print(f"   {len(df_razao)} lançamentos | Histórico[0]: {df_razao[hist_col].iloc[0]}")

# 3. Parse Extrato
print("🏦 Lendo Extrato XLS...")
ep = ExtratoParser()
df_extrato = ep.carregar(XLS_EXTRATO)
print(f"   {len(df_extrato)} lançamentos")

# 4. Engine de conciliação (mesmo fluxo do dashboard)
print("⚙️  Executando conciliação...")
engine = ConciliacaoEngine(score_minimo_similaridade=70, usar_similaridade=True, db_manager=db)
df_resultado = engine.conciliar(df_razao, df_extrato)
conc = (df_resultado["status"] == "CONCILIADO").sum()
print(f"   ✅ {len(df_resultado)} registros | Conciliados: {conc}")

# 5. Salva Razão e Extrato no banco
print("💾 Salvando no banco...")
db.importar_razao(df_razao, arquivo="Razao_Bellfone_01.2026.pdf",
                  empresa=meta.get("empresa", ""), cnpj=meta.get("cnpj", ""),
                  cliente_id=CLIENTE_ID)
db.importar_extrato(df_extrato, arquivo="extrato banco do brasil.xls",
                    cliente_id=CLIENTE_ID,
                    banco=getattr(ep, "banco", ""),
                    agencia=getattr(ep, "agencia", ""),
                    conta=getattr(ep, "conta", ""))

# 6. Salva conciliações
try:
    db.salvar_conciliacoes(df_resultado, cliente_id=CLIENTE_ID)
    print("   ✅ Conciliações salvas")
except Exception as e:
    print(f"   ⚠️  salvar_conciliacoes: {e}")

# 7. Padrões ML
try:
    db.registrar_padroes_batch(df_resultado)
    db.registrar_padroes_globais_batch(df_resultado)
    print("   ✅ Padrões ML atualizados")
except Exception as e:
    print(f"   ⚠️  padrões: {e}")

print("\n🎉 Reimportação concluída!")
