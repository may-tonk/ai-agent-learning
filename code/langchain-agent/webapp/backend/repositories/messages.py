"""
【v2 网页版新增 · 阶段 4】消息表的读写（数据层）：页面上显示的聊天记录

一行 = 页面上的一个气泡：
    role = user       data = {"text": "用户说的话"}
    role = assistant  data = {"text", "tools", "sources", "pending", "decision", "stopped", "error"}（由 streaming/recorder.py 整理）
data 存成 JSON 字符串：这些字段只用来显示，不会按它们查询，放一个 JSON 列比拆成很多列 / 很多张表简单（真实项目也常这么做）

谁用它：routers/chat.py（每轮写入）、routers/threads.py（读历史）
"""
import json

import aiosqlite

from webapp.backend.repositories.threads import now


class MessageRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def add(self, thread_id: str, role: str, data: dict) -> int:
        """
        追加一条消息，返回它的 id（resume 之后要按 id 更新同一条客服消息）。
        ensure_ascii=False：中文按原样存，不变成 \\u4e2d 这种转义（数据库里直接能看懂）
        """
        cur = await self.conn.execute(
            "INSERT INTO messages (thread_id, role, data, created_at) VALUES (?, ?, ?, ?)",
            (thread_id, role, json.dumps(data, ensure_ascii=False), now()),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def update(self, message_id: int, data: dict) -> None:
        """改一条消息的内容（审批之后，同一个气泡里接着显示后面的过程）"""
        await self.conn.execute(
            "UPDATE messages SET data = ? WHERE id = ?", (json.dumps(data, ensure_ascii=False), message_id)
        )
        await self.conn.commit()

    async def list_by_thread(self, thread_id: str) -> list[dict]:
        """一个会话的全部消息，按发生顺序。返回 [{id, role, ...data 里的字段}]，正好是前端 MessageBubble 要的形状"""
        async with self.conn.execute(
            "SELECT id, role, data FROM messages WHERE thread_id = ? ORDER BY id", (thread_id,)
        ) as cur:
            rows = await cur.fetchall()
        return [{"id": r["id"], "role": r["role"], **json.loads(r["data"])} for r in rows]

    async def last_assistant(self, thread_id: str) -> tuple[int, dict] | None:
        """最后一条客服消息 (id, data)：停在审批上的就是它，resume 时在它上面接着写；没有返回 None"""
        async with self.conn.execute(
            "SELECT id, data FROM messages WHERE thread_id = ? AND role = 'assistant' ORDER BY id DESC LIMIT 1",
            (thread_id,),
        ) as cur:
            row = await cur.fetchone()
        return (row["id"], json.loads(row["data"])) if row else None

    async def count(self, thread_id: str) -> int:
        """【阶段 5】这段对话有几条消息（小结表记下生成时的条数，对比它就知道小结之后有没有新消息）"""
        async with self.conn.execute("SELECT COUNT(*) FROM messages WHERE thread_id = ?", (thread_id,)) as cur:
            row = await cur.fetchone()
        return row[0]
