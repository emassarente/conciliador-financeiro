"""
Ponto de entrada principal para Streamlit Cloud
"""
import sys
from pathlib import Path

# Adiciona o diretório raiz ao path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# Executa o dashboard diretamente
exec(open(ROOT / "ui" / "dashboard.py", encoding="utf-8").read())
