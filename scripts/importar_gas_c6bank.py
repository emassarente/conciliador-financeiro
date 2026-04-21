"""
Script para importar extratos C6 Bank da empresa G A S TRANSPORTES.
Uso: python scripts/importar_gas_c6bank.py
"""
import sys
from pathlib import Path

# Adiciona o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.db_manager import DatabaseManager
from import_.extrato_c6bank_parser import C6BankParser


def main():
    db = DatabaseManager()
    
    # 1. Garante que a empresa G A S existe
    with db._conn() as c:
        existe = c.execute("SELECT id FROM clientes WHERE cnpj='29.450.143/0001-87'").fetchone()
        if existe:
            gas_id = existe[0]
            print(f"✓ Empresa G A S já existe (ID: {gas_id})")
        else:
            cur = c.execute("""
                INSERT INTO clientes (nome, cnpj, ativo)
                VALUES ('G A S TRANSPORTES', '29.450.143/0001-87', 1)
            """)
            gas_id = cur.lastrowid
            print(f"✓ Empresa G A S criada (ID: {gas_id})")
        
        # Vincula à União Contabilidade
        uniao = c.execute("SELECT id FROM escritorio WHERE nome='União Contabilidade Consultiva'").fetchone()
        if uniao:
            c.execute("""
                INSERT OR IGNORE INTO escritorio_clientes (escritorio_id, cliente_id)
                VALUES (?, ?)
            """, (uniao[0], gas_id))
            print(f"✓ G A S vinculada à União Contabilidade")
    
    # 2. Processa PDFs na pasta data/extratos_gas/
    pasta_extratos = Path(__file__).parent.parent / "data/extratos_gas"
    pdfs = list(pasta_extratos.glob("*.pdf"))
    
    if not pdfs:
        print(f"⚠️  Nenhum PDF encontrado em {pasta_extratos}")
        return
    
    print(f"\n📄 Encontrados {len(pdfs)} arquivo(s) PDF")
    
    senha = "294501"
    total_importados = 0
    
    for pdf_path in pdfs:
        print(f"\n{'='*60}")
        print(f"Processando: {pdf_path.name}")
        print(f"{'='*60}")
        
        try:
            parser = C6BankParser(pdf_path, senha=senha)
            lancamentos = parser.parse()
            
            print(f"  Empresa: {parser.empresa_nome}")
            print(f"  CNPJ: {parser.cnpj}")
            print(f"  Período: {parser.periodo_inicio.date()} a {parser.periodo_fim.date()}")
            print(f"  Lançamentos extraídos: {len(lancamentos)}")
            
            # 3. Converte para DataFrame
            import pandas as pd
            df_extrato = pd.DataFrame([{
                "data_lancamento": lanc["data"],
                "descricao": lanc["descricao"],
                "valor": abs(lanc["valor"]),
                "natureza": lanc["natureza"],
            } for lanc in lancamentos])
            
            # 4. Salva no banco usando importar_extrato
            importacao_id = db.importar_extrato(
                df=df_extrato,
                arquivo=pdf_path.name,
                cliente_id=gas_id,
                banco="C6 Bank",
                agencia="1",
                conta="344234312",
            )
            
            print(f"  ✅ {len(lancamentos)} lançamentos salvos (importação #{importacao_id})")
            total_importados += len(lancamentos)
            
        except Exception as e:
            print(f"  ❌ Erro ao processar {pdf_path.name}: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'='*60}")
    print(f"✅ Importação concluída: {total_importados} lançamentos no total")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
