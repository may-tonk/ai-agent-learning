"""
pytest 的公共配置：每个测试用独立的临时工单文件，测试之间互不影响，也不会改到 data/runtime/
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# 和 lessons/_common.py 一样：强制把本项目根目录放到 sys.path 第 0 位，
# 防止 PyCharm 把实验6 等其他项目也加进 PYTHONPATH 时，import 到别人的同名 utils/agent 包。
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != ROOT]
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_tickets(tmp_path, monkeypatch):
    from utils.config_handler import agent_conf

    monkeypatch.setitem(agent_conf["data"], "tickets", str(tmp_path / "tickets.json"))
    yield
