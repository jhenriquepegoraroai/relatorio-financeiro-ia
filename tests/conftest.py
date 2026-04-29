import sys
from pathlib import Path

# garante que o root do projeto esteja no path ao rodar pytest de qualquer diretório
sys.path.insert(0, str(Path(__file__).parent.parent))
