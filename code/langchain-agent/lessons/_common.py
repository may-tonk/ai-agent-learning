"""
lessons 脚本的公共部分

1. 把项目根目录加入 sys.path：在 lessons/ 目录里直接运行脚本时，Python 默认只认识 lessons/ 这一层，
   不加这一行就 import 不到 model、agent、services 这些项目模块。
2. 统一的打印格式和「只运行某一节」的命令行参数。
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 不管 sys.path 里原来有没有本项目根目录，都先删掉再放到第 0 位。
# 原因：PyCharm 会把所有标成 Sources Root 的目录加进 PYTHONPATH，实验6 也有 utils/、agent/、model/
# 这些同名包。如果只写“没有才加”，本项目根目录可能已经排在实验6 后面，
# import utils 就会拿到实验6 的 utils，报 ImportError: cannot import name 'model_conf'。
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != ROOT]
sys.path.insert(0, str(ROOT))

# Windows 的命令行默认不认识颜色控制符，执行一次空命令就能打开（PyCharm 里不需要，但不影响）
if os.name == "nt":
    os.system("")


def title(text: str) -> None:
    print("\n" + "=" * 70)
    print(text)
    print("=" * 70)


def note(text: str) -> None:
    print(f"\033[90m  ↳ {text}\033[0m")


def run_parts(parts: dict, description: str) -> None:
    """
    parts：{编号: 函数}。
    python lessons/01_models.py           运行全部
    python lessons/01_models.py --part 3  只运行第 3 节
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--part", type=int, help="只运行某一节")
    args = parser.parse_args()

    for number, func in parts.items():
        if args.part is None or args.part == number:
            func()
