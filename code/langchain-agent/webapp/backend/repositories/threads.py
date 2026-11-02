"""
【v2 网页版新增 · 阶段 4】会话表的读写（数据层）

【为什么要有「数据层」（repository，仓库）】
    路由函数里不直接写 SQL，而是调用这里的方法：threads.create(...)、threads.list_by_user(...)。
    好处：① SQL 集中在一处，表结构变了只改这里；② 路由读起来像业务逻辑，不被 SQL 打断；
         ③ 以后从 SQLite 换成 Ubuntu 上的 PostgreSQL，路由一行不用改。真实项目基本都这样分层。
    类比：路由是「窗口办事员」，仓库是「档案室管理员」—— 办事员只说「把张三的档案拿来」，不用自己进档案室翻柜子。

谁用它：routers/chat.py（新建会话、更新时间、权限检查）、routers/threads.py（列表、删除）
表结构见 webapp/backend/db.py
"""
from datetime import datetime

import aiosqlite


def now() -> str:
    """当前时间，存成「2026-10-29T16:30:05」这样的字符串（SQLite 没有专门的时间类型，字符串按字典序排就是时间顺序）"""
    return datetime.now().isoformat(timespec="seconds")


class ThreadRepository:
    def __init__(self, conn: aiosqlite.Connection):
        # 整个后端共用一个连接（app.py 启动时打开），每个方法用它执行 SQL
        self.conn = conn

    async def create(self, thread_id: str, user_id: str, title: str) -> None:
        """新建会话（发第一句话时调用）。title 取第一句话的前 30 个字，换行换成空格，列表里一行显示得下"""
        t = now()
        title = " ".join(title.split())[:30] or "新会话"
        # 问号是「参数占位符」：值由 aiosqlite 安全地填进去。
        # 注意：绝对不要用 f"... VALUES ('{title}')" 拼 SQL —— 用户输入里带个单引号就能篡改 SQL（SQL 注入）
        await self.conn.execute(
            "INSERT INTO threads (thread_id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (thread_id, user_id, title, t, t),
        )
        await self.conn.commit()

    async def get(self, thread_id: str) -> dict | None:
        """按 ID 取一个会话；不存在返回 None"""
        async with self.conn.execute("SELECT * FROM threads WHERE thread_id = ?", (thread_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def list_by_user(self, user_id: str) -> list[dict]:
        """某个用户的全部会话，最近聊过的排在最前面（对应 db.py 里的索引 idx_threads_user）"""
        async with self.conn.execute(
            "SELECT * FROM threads WHERE user_id = ? ORDER BY updated_at DESC, created_at DESC", (user_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def touch(self, thread_id: str) -> None:
        """更新「最后对话时间」：每轮对话结束时调用，这个会话就排到列表最上面"""
        await self.conn.execute("UPDATE threads SET updated_at = ? WHERE thread_id = ?", (now(), thread_id))
        await self.conn.commit()

    async def delete(self, thread_id: str) -> None:
        """
        删除会话和它的全部聊天记录。
        几条 DELETE 在同一个事务里（中间不 commit）：要么都删掉，要么都不删，不会出现「会话没了、消息还在」
        checkpointer 里的存档由路由另外删除（routers/threads.py），因为那部分不归这个表管
        """
        await self.conn.execute("DELETE FROM messages WHERE thread_id = ?", (thread_id,))
        await self.conn.execute("DELETE FROM summaries WHERE thread_id = ?", (thread_id,))  # 【阶段 5】小结也一起删
        await self.conn.execute("DELETE FROM threads WHERE thread_id = ?", (thread_id,))
        await self.conn.commit()
