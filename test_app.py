import sys
from pathlib import Path

# Adiciona o diretório raiz ao path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# Agora importa e executa o dashboard
exec(open(ROOT / "ui" / "dashboard.py", encoding="utf-8").read())
