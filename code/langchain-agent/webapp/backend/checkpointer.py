"""
【v2 网页版新增】按配置创建 checkpointer（短期记忆存在哪）

【checkpointer 是什么】agent 每走一步（模型、工具、中间件节点），就把这段对话的整个 State
（messages、current_order_id、token_usage）存成一个「检查点」，按 thread_id 分开存。
下一次同一个 thread_id 来提问，agent 先从这里读出上次的 State，再把新消息接在后面 —— 这就是短期记忆。
命令行版用的是 InMemorySaver（存在内存，程序一关就没了）；网页版换成 SQLite 文件，重启后端也不丢。

【在整体流程里的位置】
    app.py 的 lifespan（后端启动时执行一次）→ async with open_checkpointer(配置) as saver
    → build_agent(checkpointer=saver) → 之后每个请求的 ainvoke 都通过它读写记忆
    后端关闭时 async with 结束 → SQLite 连接被关掉
谁调用：只有 webapp/backend/app.py

【为什么写成「异步上下文管理器」（@asynccontextmanager + async with）】
AsyncSqliteSaver 背后有一个打开的数据库连接，用完必须关。
真实项目里「有连接要关」的资源（数据库、HTTP 客户端）都用 with 管理：进入时打开，退出时保证关闭，
即使中间出错也会关。FastAPI 的 lifespan 正好是「启动 → 运行 → 关闭」的形状，两者配合最自然。
"""
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
# Async 版本：网页后端是异步的（ainvoke），必须用 AsyncSqliteSaver。
# 注意：同步的 SqliteSaver 放在异步流程里会报错（它没有 aget_tuple / aput 这些异步方法）
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from utils.logger_handler import logger
from utils.path_tool import get_abs_path


@asynccontextmanager
async def open_checkpointer(conf: dict) -> AsyncIterator[BaseCheckpointSaver]:
    """
    按配置打开一个 checkpointer，用 async with 使用，退出时自动关闭。

    conf：web.yml 的 checkpointer 段，例如 {"kind": "sqlite", "sqlite_path": "webapp/backend/runtime/app.db"}
          kind = memory → InMemorySaver（测试用，重启就没）
          kind = sqlite → AsyncSqliteSaver（存到 sqlite_path 指定的文件）
    返回（yield 出去的）：checkpointer 对象，交给 build_agent(checkpointer=...)
    异常：kind 写错 → ValueError，后端启动直接失败（配置错了应该第一时间暴露，而不是跑起来再出怪问题）

    用法：
        async with open_checkpointer({"kind": "sqlite", ...}) as saver:
            agent = build_agent(checkpointer=saver)
            ...  # 在这里面处理请求
        # 出了 with，数据库连接已经关闭
    """
    kind = conf.get("kind", "memory")

    if kind == "memory":
        logger.info("[checkpointer] 使用内存（InMemorySaver），重启后端后记忆会丢失")
        # 内存版没有连接要关，直接交出去即可
        yield InMemorySaver()
        return

    if kind == "sqlite":
        # normpath：把配置里的 / 统一成 Windows 的 \（不加也能用，只是日志里斜杠混着很难看）
        path = os.path.normpath(get_abs_path(conf["sqlite_path"]))
        # SQLite 只会自动创建「文件」，不会创建「文件夹」；runtime/ 不存在时先建好
        os.makedirs(os.path.dirname(path), exist_ok=True)
        logger.info(f"[checkpointer] 使用 SQLite：{path}")
        # from_conn_string：按文件路径打开（文件不存在会自动创建），返回的是一个 async with 对象
        # 第一次读写时会自动建表（checkpoints、writes 两张表），不用自己写建表 SQL
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            yield saver
        # 走到这里说明 async with 已结束：连接已关闭
        return

    raise ValueError(f"web.yml 里 checkpointer.kind 只能是 memory / sqlite，现在是 {kind!r}")
