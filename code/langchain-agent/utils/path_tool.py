"""
为整个工程提供统一的绝对路径

【在整体流程里的位置】最底层的工具函数，不依赖项目里任何其他模块。
谁调用它：utils/config_handler.py（找 config/*.yml）、utils/prompt_loader.py（找 prompts/*.txt）、
          utils/logger_handler.py（找 logs/）、services/data_store.py（找 data/*.json）
为什么需要它：如果直接写相对路径 "config/model.yml"，它是相对「当前终端所在目录」解析的，
              在 lessons/ 目录下运行或在 PyCharm 里换了工作目录就会找不到文件。
              统一用「本文件位置 → 项目根目录」来拼路径，在哪里运行都一样。
"""
import os

def get_project_root() -> str:
    """
    获取工程所在的根目录（即 langchain-agent/）
    原理：本文件在 <根目录>/utils/path_tool.py，往上走两层就是根目录
    :return: 根目录的绝对路径字符串，例如 E:\\agent学习任务\\code\\langchain-agent
    """
    # 当前文件的绝对路径
    current_file= os.path.abspath(__file__)
    # 获取工程的根目录，先获取文件所在的文件夹的绝对路径
    current_dir=os.path.dirname(current_file)
    # 获取工程根目录
    project_root=os.path.dirname(current_dir)

    return project_root

def get_abs_path(relative_path:str)->str:
    """
    传递相对路径，得到绝对路径
    :param relative_path: 相对「项目根目录」的路径，例如 "config/model.yml"、"data/orders.json"
    :return: 拼好的绝对路径（只拼字符串，不检查文件是否存在）
    """
    project_root=get_project_root()
    return os.path.join(project_root,relative_path)

if __name__ == '__main__':
    print(get_abs_path("config/config.txt"))
