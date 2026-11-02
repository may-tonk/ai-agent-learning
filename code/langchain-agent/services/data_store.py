"""
JSON 文件读写：模拟真实项目里的数据库

真实项目里这一层是 MySQL / PostgreSQL 的访问代码；这里用 JSON 文件代替，
但 services 只通过这两个函数读写数据，以后换成数据库只改这个文件。

【在整体流程里的位置】最底层：tools → services → 本文件 → data/*.json
谁调用它：services/user_service、order_service、warranty_service、ticket_service
每次调用都会重新读文件（没有缓存），所以手动改 data/*.json 后不用重启就能生效。
"""
import json
import os

from utils.config_handler import agent_conf
from utils.path_tool import get_abs_path


def data_path(name: str) -> str:
    """
    name 是 config/agent.yml 里 data 段的键：users / orders / warranty_rules / tickets
    返回：对应 json 文件的绝对路径
    """
    return get_abs_path(agent_conf["data"][name])


def read_json(name: str, default=None):
    """
    读取一个数据文件。
    name：同 data_path
    default：文件不存在时返回的值（例如还没建过工单时 tickets.json 不存在，返回 []）
    返回：json 解析后的 Python 对象（列表或字典）
    """
    path = data_path(name)
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(name: str, data) -> None:
    """
    把整个数据对象写回文件（整体覆盖，不是追加）。目前只有 ticket_service 会调用（建工单、改状态）。
    name：同 data_path
    data：要保存的列表或字典
    """
    path = data_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 先写临时文件再改名：写到一半程序崩了，原文件也不会被写坏
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        # ensure_ascii=False：中文原样保存，打开文件能直接看懂；indent=2：格式化缩进，方便人看
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
