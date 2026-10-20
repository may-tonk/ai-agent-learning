"""工具包入口：按名字取一组工具。agent 循环和脚本只通过 get_toolset 拿工具，不直接依赖具体模块。"""


def get_toolset(name):
    """返回 (Toolset, 写进提示词的"数据获取方式"说明)。"""
    if name == "v1":
        from tools import v1_naive as mod
    elif name == "v2":
        from tools import v2 as mod
    else:
        raise ValueError(f"未知的工具集 {name}，可选 v1 / v2")
    return mod.TOOLSET, mod.DATA_ACCESS
