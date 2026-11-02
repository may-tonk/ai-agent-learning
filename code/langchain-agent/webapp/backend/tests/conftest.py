"""
【v2 网页版新增】后端测试的公共配置

和根目录 tests/conftest.py 做的事一样（conftest 只对自己所在的文件夹生效，所以这里要再写一份）：
    ① 把项目根目录放到 sys.path 第 0 位，保证 import 的是本项目的 agent/、services/
    ② 每个测试用独立的临时工单文件，不会改到 data/runtime/
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]  # tests → backend → webapp → langchain-agent
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != ROOT]
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_tickets(tmp_path, monkeypatch):
    from utils.config_handler import agent_conf

    monkeypatch.setitem(agent_conf["data"], "tickets", str(tmp_path / "tickets.json"))
    yield
