"""
【v2 网页版新增 · 阶段 4】会话接口：左侧会话列表、切换会话加载历史、State 面板、删除会话
    GET    /api/threads                    当前用户的会话列表（最近聊过的在前）
    GET    /api/threads/{thread_id}/messages  这段对话的聊天记录（刷新、切换会话时显示回来）
    GET    /api/threads/{thread_id}/state     checkpointer 存档里的 State：当前订单、累计 token、存档消息数
    DELETE /api/threads/{thread_id}          删除会话：会话表、消息表、checkpointer 存档三处都删
    GET    /api/threads/{thread_id}/chain     【阶段 5】checkpointer 里的原始消息链（「消息链」调试面板，对应命令行版 /history）

【在整体流程里的位置】
    React 页面：选用户 → GET /api/threads 画出列表 → 点某个会话 → GET .../messages 显示历史、GET .../state 更新侧边栏
    → 接着聊还是走 routers/chat.py 的 /api/chat/stream（带上这个 thread_id）
    → 点垃圾桶并确认 → DELETE /api/threads/{id}

【聊天记录从哪来：消息表，不是 checkpointer】原因见 webapp/backend/db.py 开头的说明
    /messages 读消息表（给人看的，完整）；/state 读 checkpointer（给模型看的，可能被摘要压缩过）
    两个数字对照着看：对话很长以后，「存档消息数」会比页面上的气泡少，那就是摘要中间件在起作用。
"""
from fastapi import APIRouter, Depends, Response
from langchain_core.messages import AIMessage, ToolMessage

from agent.state import UserContext
from utils.logger_handler import logger
from webapp.backend.deps import get_agent, get_current_user, get_messages, get_owned_thread, get_threads
from webapp.backend.repositories.messages import MessageRepository
from webapp.backend.repositories.threads import ThreadRepository
from webapp.backend.schemas import ChainMessage, HistoryMessage, ThreadInfo, ThreadState

router = APIRouter(prefix="/threads", tags=["会话"])


@router.get("", response_model=list[ThreadInfo])
async def list_threads(
    user: UserContext = Depends(get_current_user),
    threads: ThreadRepository = Depends(get_threads),
) -> list[ThreadInfo]:
    """当前用户的全部会话。只查自己的（WHERE user_id = 当前用户），别人的会话根本不会出现在结果里"""
    return [ThreadInfo(**t) for t in await threads.list_by_user(user.user_id)]


@router.get("/{thread_id}/messages", response_model=list[HistoryMessage])
async def list_messages(
    # get_owned_thread：从路径取 thread_id 并检查归属（不存在 404、别人的 403），见 deps.py
    thread_id: str = Depends(get_owned_thread),
    messages: MessageRepository = Depends(get_messages),
) -> list[dict]:
    """这段对话的全部消息，按发生顺序。返回的字典由 response_model 按 HistoryMessage 校验、补默认值"""
    return await messages.list_by_thread(thread_id)


@router.get("/{thread_id}/state", response_model=ThreadState)
async def get_thread_state(thread_id: str = Depends(get_owned_thread), agent=Depends(get_agent)) -> ThreadState:
    """
    checkpointer 存档里的 State（和命令行版 /state 命令看到的是同一份数据）。
    snapshot.values 就是 CustomerServiceState：messages、current_order_id、token_usage（见 agent/state.py）
    """
    snapshot = await agent.aget_state({"configurable": {"thread_id": thread_id}})
    values = snapshot.values
    return ThreadState(
        thread_id=thread_id,
        current_order_id=values.get("current_order_id"),
        token_usage=values.get("token_usage"),
        memory_messages=len(values.get("messages", [])),
    )


# 【阶段 5】消息链里每条消息的文字最多显示多少字（知识库检索结果动辄上千字，全显示面板就没法看了）
CHAIN_TEXT_LIMIT = 300


@router.get("/{thread_id}/chain", response_model=list[ChainMessage])
async def get_thread_chain(thread_id: str = Depends(get_owned_thread), agent=Depends(get_agent)) -> list[ChainMessage]:
    """
    【阶段 5】checkpointer 存档里的原始消息链：模型下次被调用时，实际看到的就是这些消息（加上系统提示词）。
    和 /messages（聊天记录）对照着看：
        聊天记录里一个客服气泡 = 这里的好几条：ai（请求工具，带 tool_calls）→ tool（结果，带 tool_call_id）→ ai（最终回答）
        对话很长以后，前面的消息会被 SummarizationMiddleware 换成一条摘要（is_summary=true）
    这是给开发者看的调试接口，真实项目里一般只对管理员开放，或者只在开发环境打开。
    """
    snapshot = await agent.aget_state({"configurable": {"thread_id": thread_id}})
    chain = []
    for i, m in enumerate(snapshot.values.get("messages", [])):
        text = m.text
        chain.append(
            ChainMessage(
                index=i,
                type=m.type,  # LangChain 每种消息类都有 type：HumanMessage → "human"，AIMessage → "ai"，ToolMessage → "tool"
                text=text[:CHAIN_TEXT_LIMIT],
                length=len(text),
                # tool_calls 里的每一项是字典 {name, args, id, type}，只取面板要显示的三个
                tool_calls=[{"id": c["id"], "name": c["name"], "args": c["args"]} for c in m.tool_calls]
                if isinstance(m, AIMessage)
                else [],
                tool_call_id=m.tool_call_id if isinstance(m, ToolMessage) else None,
                tool_name=m.name if isinstance(m, ToolMessage) else None,
                status=m.status if isinstance(m, ToolMessage) else None,
                # 摘要消息的标记，见 services/summary_service.py 的 _render_transcript
                is_summary=m.additional_kwargs.get("lc_source") == "summarization",
            )
        )
    return chain


@router.delete("/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: str = Depends(get_owned_thread),
    agent=Depends(get_agent),
    threads: ThreadRepository = Depends(get_threads),
) -> Response:
    """
    删除会话。三处都要删，少删一处都会留下「删了但其实还在」的数据：
        ① checkpointer 存档（给模型的记忆）：adelete_thread 是 LangGraph checkpointer 自带的方法，删掉这个 thread 的全部检查点
        ② 消息表、③ 会话表：ThreadRepository.delete 在一个事务里一起删
    状态码 204 = 「成功了，但没有内容要返回」，删除接口的惯例。
    注意：真实项目常做「软删除」（加一列 deleted_at，只是不显示），方便误删恢复和审计；这里是真删，删了就找不回来，
        所以前端要先弹窗确认。
    """
    await agent.checkpointer.adelete_thread(thread_id)
    await threads.delete(thread_id)
    logger.info(f"[网页] 删除会话 {thread_id}")
    return Response(status_code=204)
