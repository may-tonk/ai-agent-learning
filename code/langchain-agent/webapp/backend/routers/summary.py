"""
【v2 网页版新增 · 阶段 5】会话小结接口（对应命令行版的 /summary 命令）
    POST /api/threads/{thread_id}/summary  生成小结（调用一次 DeepSeek），存进小结表，返回给页面
    GET  /api/threads/{thread_id}/summary  读已经存好的小结（打开会话时显示）；还没生成过返回 null

【在整体流程里的位置】
    页面顶部点「生成小结」→ POST 本接口
    → agent.aget_state 读 checkpointer 里这段对话的消息（含工具结果，工单号就在里面）
    → services/summary_service.asummarize_session：拼对话稿 → with_structured_output(ServiceSummary) → DeepSeek
    → 小结表 summaries 存一份（repositories/summaries.py）→ 返回 SummaryResponse → 页面显示小结卡片

【为什么从 checkpointer 读消息，而不是消息表】
    消息表是给人看的气泡：有工具名和参数，但没有工具结果（比如创建报修单返回的工单号）；
    checkpointer 里是给模型看的完整消息链，工具结果都在 —— 小结里的 ticket_ids 就要从这里来。
    对话很长被摘要压缩过的部分，以摘要的形式也还在（summary_service 会标出来）。

【出错怎么办】小结生成失败不影响对话，页面上显示一句提示即可：
    对话还是空的 → 400；模型没按格式返回 → 502；DeepSeek 限流 / 超时 / 连不上 → 429 / 504 / 502（webapp/backend/errors.py）
    失败时不保存，之前存的旧小结保持不变
"""
from fastapi import APIRouter, Depends, HTTPException
from langchain_core.exceptions import ModelError

from services.errors import RuleViolationError, SummaryError
from services.summary_service import asummarize_session
from utils.logger_handler import logger
from webapp.backend.deps import get_agent, get_messages, get_owned_thread, get_summaries, get_summary_model
from webapp.backend.errors import model_error_to_http
from webapp.backend.repositories.messages import MessageRepository
from webapp.backend.repositories.summaries import SummaryRepository
from webapp.backend.schemas import SummaryResponse

router = APIRouter(prefix="/threads", tags=["小结"])


@router.get("/{thread_id}/summary", response_model=SummaryResponse | None)
async def get_summary(
    thread_id: str = Depends(get_owned_thread),
    summaries: SummaryRepository = Depends(get_summaries),
    messages: MessageRepository = Depends(get_messages),
) -> SummaryResponse | None:
    """
    读存好的小结。还没生成过返回 null（状态码 200），而不是 404：
        「还没有小结」是正常情况，不是错误；返回 404 的话浏览器控制台每打开一个会话就会多一条红色报错
    """
    saved = await summaries.get(thread_id)
    if saved is None:
        return None
    # 过期判断：现在的消息条数比生成时多 → 之后又聊过
    return SummaryResponse(**saved, stale=await messages.count(thread_id) > saved["message_count"])


@router.post("/{thread_id}/summary", response_model=SummaryResponse)
async def create_summary(
    thread_id: str = Depends(get_owned_thread),
    agent=Depends(get_agent),
    model=Depends(get_summary_model),
    summaries: SummaryRepository = Depends(get_summaries),
    messages: MessageRepository = Depends(get_messages),
) -> SummaryResponse:
    """生成（或重新生成）小结。会调用一次 DeepSeek，通常要几秒"""
    # 先记下现在有几条消息，再调模型：生成的这几秒里如果又有新消息，下次读的时候就会显示「已过期」
    message_count = await messages.count(thread_id)
    snapshot = await agent.aget_state({"configurable": {"thread_id": thread_id}})
    try:
        result = await asummarize_session(snapshot.values.get("messages", []), model=model)
    except RuleViolationError as e:
        # 对话为空：请求本身不成立（400）
        raise HTTPException(status_code=400, detail=str(e))
    except SummaryError as e:
        # 模型没按格式返回：上游的问题（502），用户点「重新生成」可能就好了
        raise HTTPException(status_code=502, detail=str(e))
    except ModelError as e:
        logger.error(f"[小结] 调用模型失败：{type(e).__name__}: {e}")
        raise model_error_to_http(e)

    data = result.model_dump()
    created_at = await summaries.save(thread_id, data, message_count)
    logger.info(f"[小结] {thread_id} 已生成：{data['category']}，resolved={data['resolved']}")
    return SummaryResponse(summary=data, created_at=created_at, message_count=message_count, stale=False)
