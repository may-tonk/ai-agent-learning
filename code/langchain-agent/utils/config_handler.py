"""
读取 config/ 下的 yml 配置

和实验6 的区别：实验6 每个 yml 写了一个几乎一样的 load_xxx_config 函数，
这里合并成一个通用的 load_yaml，新增配置文件时只需要加一行，不用复制函数。

【在整体流程里的位置】程序启动时第一次被 import 就把 4 个 yml 读进内存，变成 4 个普通字典：
    model_conf   ← config/model.yml   → model/factory.py 用（创建聊天模型、向量模型）
    agent_conf   ← config/agent.yml   → agent/agent.py、agent/middleware.py、services/data_store.py 用
    chroma_conf  ← config/chroma.yml  → services/kb_service.py 用
    prompts_conf ← config/prompts.yml → utils/prompt_loader.py 用
注意：只在启动时读一次，程序运行中改 yml 不会生效，要重启。
"""
import yaml

from utils.path_tool import get_abs_path


def load_yaml(relative_path: str, encoding: str = "utf-8") -> dict:
    """
    读取一个 yml 文件，返回字典。

    relative_path：相对项目根目录的路径，例如 "config/model.yml"
    encoding：文件编码，配置里有中文注释，必须用 utf-8（Windows 默认 gbk 会乱码或报错）
    返回：yml 内容对应的字典；文件是空的时返回 {}（safe_load 对空文件返回 None）
    """
    # safe_load：只解析普通数据（字典、列表、字符串、数字），不会执行 yml 里的 Python 对象标签，更安全
    with open(get_abs_path(relative_path), "r", encoding=encoding) as f:
        return yaml.safe_load(f) or {}


# 模块被导入时读一次，之后所有地方共用这几个字典
# 测试里可以用 monkeypatch.setitem(agent_conf[...], ...) 临时改其中的值（见 tests/conftest.py）
model_conf = load_yaml("config/model.yml")
agent_conf = load_yaml("config/agent.yml")
chroma_conf = load_yaml("config/chroma.yml")
prompts_conf = load_yaml("config/prompts.yml")


if __name__ == "__main__":
    print(model_conf["chat"])
    print(agent_conf["role_tools"])
