"""
加载 .env 环境变量（API key、Chroma 地址等）
查找顺序：本项目目录的 .env 优先，其次向上逐级找（例如 E:\\agent学习任务\\.env）

【在整体流程里的位置】程序启动时最先执行的一步：model/factory.py 第一行 `import utils.env_loader`，
导入这个模块就会执行最下面的 load_env()，把 .env 里的变量放进 os.environ。
之后各处用 os.getenv(...) 读取：
    DEEPSEEK_API_KEY   → langchain-deepseek 自动读取，聊天模型用
    DASHSCOPE_API_KEY  → model/multimodal_embeddings.py，向量模型用
    CHROMA_HOST / CHROMA_PORT → services/kb_service.py，连接知识库用
为什么 key 放 .env 而不是 config/*.yml：key 是机密，.env 不提交 git；yml 是可以公开的调参配置。
"""
from pathlib import Path

from dotenv import load_dotenv


def load_env() -> Path | None:
    """
    从 utils/ 目录开始往上逐级找 .env 文件，找到第一个就加载并停止。

    返回：加载的 .env 文件路径；一个都没找到时返回 None（此时只能用终端里已设置的环境变量）
    谁调用：本模块导入时自动调用一次（见最后一行），不需要手动调用
    """
    current = Path(__file__).resolve().parent
    # current.parents：上一级、上上级……一直到磁盘根目录
    for directory in [current, *current.parents]:
        env_file = directory / ".env"
        if env_file.is_file():
            # override=False：终端里已经设置的环境变量优先，不被 .env 覆盖
            # 好处：临时想换 key 或换 Chroma 地址测试时，在终端 set 一下即可，不用改 .env
            load_dotenv(env_file, override=False)
            return env_file
    return None


# 模块级变量：导入时执行一次，之后可以 print(loaded_env_file) 看到底加载了哪个 .env
loaded_env_file = load_env()
