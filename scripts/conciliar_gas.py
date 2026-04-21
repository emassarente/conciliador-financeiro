"""
Executa conciliação automática para G A S TRANSPORTES usando dados já importados.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db_manager import DatabaseManager
from engine.conciliacao_engine import ConciliacaoEngine

def main():
    db = DatabaseManager()
    
    # Busca G A S
    with db._conn() as c:
        gas = c.execute("SELECT id, nome FROM clientes WHERE cnpj='29.450.143/0001-87'").fetchone()
        if not gas:
            print("❌ G A S não encontrada")
            return
        gas_id = gas[0]
        print(f"Empresa: {gas[1]} (ID: {gas_id})")
    
    # Carrega dados
    print("\n📊 Carregando dados...")
    df_extrato = db.consultar_extrato(cliente_id=gas_id)
    df_razao = db.consultar_razao(cliente_id=gas_id)
    
    # Renomeia colunas para o formato esperado pelo engine
    import pandas as pd
    if 'data_lancamento' in df_razao.columns:
        df_razao = df_razao.rename(columns={'data_lancamento': 'data_razao'})
        df_razao['data_razao'] = pd.to_datetime(df_razao['data_razao'], errors='coerce')
    if 'valor' in df_razao.columns:
        df_razao = df_razao.rename(columns={'valor': 'valor_razao'})
    if 'data_lancamento' in df_extrato.columns:
        df_extrato = df_extrato.rename(columns={'data_lancamento': 'data_extrato'})
        df_extrato['data_extrato'] = pd.to_datetime(df_extrato['data_extrato'], errors='coerce')
    if 'valor' in df_extrato.columns:
        df_extrato = df_extrato.rename(columns={'valor': 'valor_extrato'})
    
    print(f"  Extrato: {len(df_extrato)} lançamentos")
    print(f"  Razão: {len(df_razao)} lançamentos")
    
    if df_extrato.empty or df_razao.empty:
        print("❌ Sem dados para conciliar")
        return
    
    # Executa conciliação
    print("\n🚀 Executando conciliação automática...")
    engine = ConciliacaoEngine(db_manager=db)
    df_resultado = engine.conciliar(df_razao, df_extrato)
    
    print(f"\n✅ Conciliação concluída!")
    print(f"  Total de matches: {len(df_resultado)}")
    
    # Estatísticas
    if not df_resultado.empty:
        tipos = df_resultado['tipo_match'].value_counts()
        print("\n📈 Matches por tipo:")
        for tipo, count in tipos.items():
            print(f"  {tipo}: {count}")
        
        # Salva no banco (apenas os conciliados, não os NAO_CONCILIADO)
        print("\n💾 Salvando resultados...")
        df_conciliados = df_resultado[df_resultado['tipo_match'] != 'NAO_CONCILIADO'].copy()
        if not df_conciliados.empty:
            count = db.salvar_conciliacoes(df_conciliados, cliente_id=gas_id)
            print(f"✅ {len(df_conciliados)} conciliações salvas no banco")
        else:
            print("⚠️ Nenhuma conciliação para salvar")


if __name__ == "__main__":
    main()
