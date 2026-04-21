import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from database.db_manager import DatabaseManager

xlsx = Path(__file__).parent.parent / 'data/extratos_gas/razao_gas.xlsx'
df_raw = pd.read_excel(xlsx)

def parse_valor(val_str):
    if pd.isna(val_str) or val_str == '':
        return 0.0
    val_str = str(val_str).replace('.', '').replace(',', '.').replace('D', '').replace('C', '').strip()
    try:
        return float(val_str)
    except:
        return 0.0

df_razao = pd.DataFrame({
    'data_razao': pd.to_datetime(df_raw['data'], format='%d/%m/%Y', errors='coerce'),
    'historico': df_raw['historico'].fillna(''),
    'lote': df_raw['lote'].fillna(''),
    'debito': df_raw['debito'].apply(parse_valor),
    'credito': df_raw['credito'].apply(parse_valor),
    'saldo': df_raw['saldo'].apply(lambda x: parse_valor(str(x).replace('D', '').replace('C', ''))),
    'conta_codigo': '1.1.1.02.000008',
    'conta_nome': 'BANCO C6',
})

df_razao = df_razao[df_razao['data_razao'].notna()].copy()
df_razao['valor_razao'] = df_razao.apply(lambda r: r['debito'] if r['debito'] > 0 else r['credito'], axis=1)

print(f"Lançamentos: {len(df_razao)}")

db = DatabaseManager()
gas = db._conn().execute("SELECT id FROM clientes WHERE cnpj='29.450.143/0001-87'").fetchone()
importacao_id = db.importar_razao(df=df_razao, arquivo='razao_gas.xlsx', cliente_id=gas[0])
print(f"✅ Importado #{importacao_id}")
