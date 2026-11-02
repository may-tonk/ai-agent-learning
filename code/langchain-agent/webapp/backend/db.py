"""
【v2 网页版新增 · 阶段 4】业务数据库：会话表（threads）和消息表（messages）；阶段 5 加了小结表（summaries）

【为什么 checkpointer 之外还要自己建表】
    checkpointer 存的是「agent 的工作记忆」：给模型看的 State，会被改写 ——
        SummarizationMiddleware 在历史超过 6000 token 时，会把旧消息压缩成一段摘要，原文就从 State 里消失了；
        「停止」后补的 ToolMessage、拒绝理由变成的 ToolMessage，也都是给模型看的，不是给人看的。
    页面要显示的是「聊天记录」：用户说了什么、客服回了什么、调了哪些工具、点过什么审批，一条都不能少。
    两者用途不同，真实项目都会分开存：checkpointer（或 Redis）放给模型的上下文，业务库放聊天记录、会话列表。
    类比：checkpointer 是医生脑子里「这个病人现在的情况」，会简化；消息表是病历本，原样记下每次就诊。

【在整体流程里的位置】
    app.py 的 lifespan 启动时 async with open_db(路径) as conn → 交给 repositories/ 里的两个仓库类
    → routers/chat.py 每轮对话读写，routers/threads.py 列出会话、读历史、删除
    存在哪：和 checkpointer 同一个 SQLite 文件（runtime/app.db），只是不同的表；测试用内存数据库（":memory:"）

为什么用 aiosqlite：后端是异步的，普通 sqlite3 查询会卡住事件循环；aiosqlite 把查询放到后台线程执行，用 await 等结果。
    （AsyncSqliteSaver 背后用的也是它，requirements.txt 里已经有了）
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite

from utils.logger_handler import logger

# 建表语句。IF NOT EXISTS：表已经有了就跳过，所以每次启动都执行一遍也没关系（不会清空数据）
SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    thread_id  TEXT PRIMARY KEY,      -- 会话 ID，和 checkpointer 里的 thread_id 是同一个
    user_id    TEXT NOT NULL,         -- 属于谁：权限检查查这一列（阶段 3 之前靠 thread_id 前缀判断）
    title      TEXT NOT NULL,         -- 标题：第一句话的前 30 个字
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL          -- 最后一次对话的时间，会话列表按它倒序排
);
-- 索引：会话列表的查询是「某个用户的会话，按更新时间排序」，建索引后不用扫全表
CREATE INDEX IF NOT EXISTS idx_threads_user ON threads (user_id, updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,  -- 自增编号，同一个会话里按它排序就是聊天顺序
    thread_id  TEXT NOT NULL,
    role       TEXT NOT NULL,         -- user / assistant
    data       TEXT NOT NULL,         -- 页面显示需要的全部内容，存成 JSON（见 streaming/recorder.py）
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages (thread_id, id);

-- 【阶段 5】会话小结：每个会话只留最新一份，重新生成就覆盖（thread_id 是主键，INSERT OR REPLACE）
CREATE TABLE IF NOT EXISTS summaries (
    thread_id     TEXT PRIMARY KEY,
    data          TEXT NOT NULL,      -- ServiceSummary 的 7 个字段，存成 JSON（见 agent/schemas.py）
    message_count INTEGER NOT NULL,   -- 生成时消息表里这段对话有几条消息；之后又多了 → 页面提示「小结已过期」
    created_at    TEXT NOT NULL
);
"""


@asynccontextmanager
async def open_db(path: str) -> AsyncIterator[aiosqlite.Connection]:
    """
    打开数据库连接并建好表，用 async with 使用，退出时自动关闭（和 checkpointer.py 的 open_checkpointer 同一个写法）。

    path：SQLite 文件路径；":memory:" = 内存数据库（测试用，连接一关数据就没了）
    返回（yield 出去的）：aiosqlite 连接，交给 repositories/ 里的仓库类
    """
    async with aiosqlite.connect(path) as conn:
        # row_factory：查询结果按列名取值（row["title"]），不用记第几列
        conn.row_factory = aiosqlite.Row
        # executescript：一次执行多条 SQL（上面的建表、建索引）
        await conn.executescript(SCHEMA)
        await conn.commit()
        logger.info(f"[数据库] 已打开：{path}")
        yield conn
