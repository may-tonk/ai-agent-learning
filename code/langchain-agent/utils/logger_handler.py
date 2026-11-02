"""
日志工具（来自实验6）：同时输出到控制台和 logs/ 下的文件

【在整体流程里的位置】几乎所有模块都会 `from utils.logger_handler import logger`，
程序启动时第一次导入就创建好全局的 logger，之后大家共用这一个对象。
你在终端里看到的「[模型调用] 输入 1513 / 输出 66 token」「[工具调用] ...」就是 agent/middleware.py 通过它打出来的。

两个输出口（Handler），级别可以分开调：
    控制台：默认 INFO 及以上 —— 想让 main.py 的对话界面更干净，可以把 console_level 改成 logging.WARNING
    文件  ：默认 DEBUG 及以上，写到 logs/agent_YYYYMMDD.log —— 排查问题时看文件，信息最全（包括被丢弃的检索结果）
日志级别从低到高：DEBUG < INFO < WARNING < ERROR，设置为某一级 = 只输出这一级及更高的
"""
import logging
from utils.path_tool import get_abs_path

import os
from datetime import time, datetime

# 日志保存的根目录
LOG_ROOT=get_abs_path("logs")

# 确保日志的目录所在
os.makedirs(LOG_ROOT,exist_ok=True)

# 日志的格式配置 error info debug
# 依次是：时间 - 日志器名 - 级别 - 哪个文件第几行打的 - 内容
DEFAULT_LOG_FORMAT= logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
)

def get_logger(
        name: str= "agent",
        console_level:int =logging.INFO,        # 只输出info级别以上的日志信息，避免debug垃圾信息
        file_level: int=logging.DEBUG,
        log_file =None,
) -> logging.Logger:
    """
    创建（或取回已创建的）日志器。

    name：日志器名字，同名只会创建一次；也会出现在每行日志里和默认的文件名里
    console_level：控制台输出的最低级别，默认 logging.INFO
    file_level：文件输出的最低级别，默认 logging.DEBUG（文件里记得更全）
    log_file：日志文件路径；不传时用 logs/<name>_<今天日期>.log，每天一个新文件
    返回：配置好的 logging.Logger
    """
    logger =logging.getLogger(name)
    # 日志器本身放行所有级别，具体过滤交给下面两个 Handler 各自的级别
    logger.setLevel(logging.DEBUG)

    # 避免重复添加Handler,如果存在,不重复打印日志
    if logger.handlers:
        return logger
    # 控制台Handler
    console_handler= logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(DEFAULT_LOG_FORMAT)

    logger.addHandler(console_handler)

    # 文件Handler
    if not log_file:            # 日志文件的存放路径
        log_file= os.path.join(LOG_ROOT,f"{name}_{datetime.now().strftime('%Y%m%d')}.log")

    file_handler=logging.FileHandler(log_file,encoding='utf-8')
    file_handler.setLevel(file_level)
    file_handler.setFormatter(DEFAULT_LOG_FORMAT)

    logger.addHandler(file_handler)

    return logger

# 快捷获取日志器
logger=get_logger()

if __name__== '__main__':
    logger.info("信息日志")
    logger.error("错误日志")
    logger.warning("警告日志")
    logger.debug("调试日志")
