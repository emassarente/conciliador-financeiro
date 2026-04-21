"""
Ponto de entrada principal para Streamlit Cloud
"""
import sys
from pathlib import Path

# Adiciona o diretório raiz ao path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# Importa e executa o dashboard
from ui import dashboard

# O Streamlit vai executar automaticamente o módulo dashboard
