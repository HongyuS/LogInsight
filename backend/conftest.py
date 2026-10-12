"""pytest 根配置: 将 backend/ 加入 sys.path, 使 `import app.*` 可用."""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))