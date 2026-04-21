"""
Script para importar Razão Contábil da G A S TRANSPORTES (formato Domínio).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db_manager import DatabaseManager
from import_.razao_parser import RazaoParser


def main():
    db = DatabaseManager()
    
    # Arquivo do Razão
    razao_xlsx = Path(__file__).parent.parent / "data/extratos_gas/razao_gas.xlsx"
    
    if not razao_xlsx.exists():
        print(f"❌ Arquivo não encontrado: {razao_xlsx}")
        return
    
    print(f"📄 Processando: {razao_xlsx.name}")
    
    # Parse
    parser = RazaoParser()
    df_razao = parser.carregar(razao_xlsx)
    
    meta = parser.obter_metadados()
    print(f"  Empresa: {meta.get('empresa', 'N/A')}")
    print(f"  CNPJ: {meta.get('cnpj', 'N/A')}")
    print(f"  Período: {meta.get('periodo_inicio', 'N/A')} a {meta.get('periodo_fim', 'N/A')}")
    print(f"  Lançamentos: {len(df_razao)}")
    
    # Busca ID da G A S
    with db._conn() as c:
        gas = c.execute("SELECT id FROM clientes WHERE cnpj='29.450.143/0001-87'").fetchone()
        if not gas:
            print("❌ Empresa G A S não encontrada no banco")
            return
        gas_id = gas[0]
    
    # Importa
    importacao_id = db.importar_razao(
        df=df_razao,
        arquivo=razao_xlsx.name,
        cliente_id=gas_id,
    )
    
    print(f"✅ {len(df_razao)} lançamentos importados (importação #{importacao_id})")


if __name__ == "__main__":
    main()
