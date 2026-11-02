"""
【v2 网页版新增 · 阶段 5】小结表的读写（数据层）：「生成小结」按钮的结果存在这里

一行 = 一个会话最新的一份小结：
    data           ServiceSummary 的字段（user_intent、category、related_orders …），存成 JSON
    message_count  生成那一刻，消息表里这段对话有几条消息
    created_at     生成时间
为什么存 message_count：之后又聊了几句，小结就不再代表整段对话了（「过期」）。
    比较「现在的条数」和「生成时的条数」就能判断，不用把对话内容再发给模型一次。

谁用它：routers/summary.py（生成后保存、打开会话时读取）；ThreadRepository.delete 删会话时一起删
"""
import json

import aiosqlite

from webapp.backend.repositories.threads import now


class SummaryRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def save(self, thread_id: str, data: dict, message_count: int) -> str:
        """
        保存小结，返回生成时间。
        INSERT OR REPLACE：thread_id 是主键，已经有小结就整行替换 —— 「重新生成」覆盖旧的，不会越存越多
        """
        created_at = now()
        await self.conn.execute(
            "INSERT OR REPLACE INTO summaries (thread_id, data, message_count, created_at) VALUES (?, ?, ?, ?)",
            (thread_id, json.dumps(data, ensure_ascii=False), message_count, created_at),
        )
        await self.conn.commit()
        return created_at

    async def get(self, thread_id: str) -> dict | None:
        """取一个会话的小结：{summary, message_count, created_at}；还没生成过返回 None"""
        async with self.conn.execute(
            "SELECT data, message_count, created_at FROM summaries WHERE thread_id = ?", (thread_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return {"summary": json.loads(row["data"]), "message_count": row["message_count"], "created_at": row["created_at"]}
