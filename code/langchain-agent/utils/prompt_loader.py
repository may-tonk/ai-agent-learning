"""
按名字读取提示词正文

代码里只写 load_prompt("system")，具体是哪个文件由 config/prompts.yml 决定。
好处：改提示词只改 .txt，换文件只改 yml，Python 代码不用动。

【在整体流程里的位置】
谁调用它：
    agent/middleware.py 的 build_system_prompt → load_prompt("system")，每次调用模型前都会调用
    services/summary_service.py 的 summarize_session → load_prompt("session_summary")，/summary 时调用
因为有 lru_cache，实际只在第一次用到时读一次磁盘。
"""
from functools import lru_cache

from utils.config_handler import prompts_conf
from utils.logger_handler import logger
from utils.path_tool import get_abs_path


@lru_cache  # 同一个提示词只读一次磁盘，之后直接用内存里的结果（副作用：运行中改 txt 不会生效，要重启）
def load_prompt(name: str) -> str:
    """
    name：config/prompts.yml 里登记的名字，目前有 "system"、"session_summary"
    返回：提示词全文（字符串）。system 提示词里带 {user_name} 这类占位符，由调用方 .format() 填充
    异常：名字没登记 → 记错误日志并抛 KeyError（拼错名字时能马上发现，而不是悄悄用空提示词）
    """
    if name not in prompts_conf:
        logger.error(f"[load_prompt] config/prompts.yml 里没有登记提示词：{name}")
        raise KeyError(name)

    path = get_abs_path(prompts_conf[name])
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    print(load_prompt("system"))
