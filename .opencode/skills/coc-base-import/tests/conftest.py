import sys
from pathlib import Path

# 脚本不是包，测试直接 import 模块名：把 scripts/ 加进 sys.path。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
