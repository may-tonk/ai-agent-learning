"""
【v2 网页版新增】对话接口
    POST /api/chat         阶段 1：不流式，等 agent 跑完一次性返回 JSON（保留给脚本和测试用）
    POST /api/chat/stream  阶段 2：流式，边跑边用 SSE 把文字和工具进度推给浏览器（页面用这个）
    POST /api/chat/resume  阶段 3：停在审批上的对话，批准 / 拒绝之后接着跑，同样用 SSE 推回去
    【阶段 4】每轮对话都写进会话表和消息表（repositories/），刷新页面后历史还能显示回来；权限改成查会话表

【在整体流程里的位置】
    React 页面点「发送」→ fetch POST /api/chat {thread_id, message}，请求头带 X-User-Id
    → deps.get_current_user 识别用户、deps.get_agent 取出 agent
    → 本文件 chat()：await agent.ainvoke(...)（中间件 → 模型 → 工具 → 模型…，记忆读写 SQLite）
    → 从 State 里整理出 回答 / 工具调用 / 参考资料 / 待审批 / token → 返回 JSON → 页面显示

它和命令行版 agent/agent.py 的 CustomerServiceSession 做的是同一件事：
    命令行：session.ask(text) → agent.stream(...)（同步，边跑边打印）
    网页  ：chat()            → await agent.ainvoke(...)（异步，跑完一次性返回）
           chat_stream()     → await agent.astream_events(..., version="v3")（异步，边跑边推，见 streaming/runner.py）
为什么网页用异步：FastAPI 在一个事件循环里同时处理很多请求；await 等 DeepSeek 回包时，
    这个请求让出 CPU，别的请求照常处理（lessons/05 第 6 节两个用户「同时」提问就是这个效果）。
"""
import uuid

import anyio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.exceptions import ModelError

from langgraph.types import Command

from agent.state import UserContext
from utils.logger_handler import logger
from webapp.backend.deps import check_thread_owner, get_agent, get_current_user, get_messages, get_threads
from webapp.backend.errors import model_error_to_http  # 【阶段 5】挪到 errors.py，小结接口也要用
from webapp.backend.repositories.messages import MessageRepository
from webapp.backend.repositories.threads import ThreadRepository
from webapp.backend.schemas import ChatRequest, ChatResponse, ResumeRequest, ToolCallInfo
from webapp.backend.streaming import protocol
from webapp.backend.streaming.recorder import TurnRecorder, empty_message
from webapp.backend.streaming.runner import stream_agent

# APIRouter：一组接口的集合。prefix="/chat" + app.py 里挂载时的 prefix="/api" → 完整路径 /api/chat
# tags：在 /docs 接口文档里分组显示用
router = APIRouter(prefix="/chat", tags=["对话"])


@router.post("", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    user: UserContext = Depends(get_current_user),
    agent=Depends(get_agent),
    threads: ThreadRepository = Depends(get_threads),
    messages: MessageRepository = Depends(get_messages),
) -> ChatResponse:
    """
    发一句话，等 agent 跑完，返回这一轮的结果。

    req：请求体，FastAPI 已经按 ChatRequest 校验过（格式不对的请求到不了这里，直接 422）
    user：当前登录用户（deps.get_current_user 从 X-User-Id 查出来的）
    agent：启动时建好的 agent（deps.get_agent 从 app.state 取出）
    返回：ChatResponse（FastAPI 按 response_model 转成 JSON）
    """
    # ①② 确定 thread_id、检查权限和审批状态（和流式接口共用，见 _prepare）
    thread_id, config = await _prepare(req, user, agent, threads)
    # 【阶段 4】用户这句话先写进消息表（检查都通过了才写，被拒绝的请求不留记录）
    await messages.add(thread_id, "user", {"text": req.message})
    # ③ 运行 agent。ainvoke = invoke 的异步版：跑完整个循环才返回最终 State
    #   参数和命令行版 agent.stream 一样：
    #     {"messages": [HumanMessage(...)]}  只传这一句新消息，历史由 checkpointer 按 thread_id 自动读出来
    #     config   带 thread_id，决定读写哪段对话的存档
    #     context  当前用户，工具和中间件通过 runtime.context 读取（模型改不了）
    try:
        await agent.ainvoke({"messages": [HumanMessage(req.message)]}, config=config, context=user)
    except ModelError as e:
        # 模型相关的错误：转成合适的 HTTP 状态码 + 用户能看懂的提示（分类和 main.py 一样）
        logger.error(f"[网页] 模型调用失败：{type(e).__name__}: {e}")
        error = model_error_to_http(e)
        # 【阶段 4】出错也留一条记录：刷新后能看到「这一句当时失败了」，而不是只剩一句没人回答的话
        await messages.add(thread_id, "assistant", {**empty_message(), "error": error.detail})
        await threads.touch(thread_id)
        raise error

    # ④ 跑完后再读一次快照：既有最终 State（values），也能看出是不是停在了审批上（tasks 里的 interrupts）
    #   为什么不直接用 ainvoke 的返回值：返回值只有 State，停在审批上时要另外从快照里取 interrupts，
    #   统一从快照取，代码只有一条路径
    snapshot = await agent.aget_state(config)
    result = _build_response(thread_id, snapshot)
    # 【阶段 4】客服的回答写进消息表，会话排到列表最上面
    await messages.add(thread_id, "assistant", TurnRecorder.from_response(result.model_dump()))
    await threads.touch(thread_id)
    return result


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    user: UserContext = Depends(get_current_user),
    agent=Depends(get_agent),
    threads: ThreadRepository = Depends(get_threads),
    messages: MessageRepository = Depends(get_messages),
) -> StreamingResponse:
    """
    【阶段 2】发一句话，边跑边把事件用 SSE 推回去（事件协议见 streaming/protocol.py）。

    参数和 chat() 完全一样；区别只在「怎么返回」：
        chat()        等跑完 → 返回一个 JSON
        chat_stream() 立刻返回一个「一直开着的响应」，agent 每产生一点东西就往里写一条事件

    【两类错误，处理方式不同】
        开始运行之前的错误（没登录 401、别人的会话 403、停在审批上 409、格式不对 422）：
            还没开始推流，照常返回 HTTP 错误状态码，前端按普通请求的错误处理
        开始推流之后的错误（模型超时、限流…）：
            响应头 200 已经发出去了，状态码改不了，只能推一条 error 事件 + done(status=error)
    """
    # ①② 和 chat() 一样的检查。注意它在 StreamingResponse 之前执行：这里抛的 HTTPException 还能变成 4xx 状态码
    thread_id, config = await _prepare(req, user, agent, threads)
    await messages.add(thread_id, "user", {"text": req.message})  # 【阶段 4】同 chat()
    # ③④ 边跑边推（和 resume 共用，见 _sse_response）；这一轮是新的客服消息，记录从空开始
    return _sse_response(
        agent, {"messages": [HumanMessage(req.message)]}, thread_id, config, user,
        recorder=TurnRecorder(), threads=threads, messages=messages,
    )


@router.post("/resume")
async def chat_resume(
    req: ResumeRequest,
    user: UserContext = Depends(get_current_user),
    agent=Depends(get_agent),
    threads: ThreadRepository = Depends(get_threads),
    messages: MessageRepository = Depends(get_messages),
) -> StreamingResponse:
    """
    【阶段 3】对话停在审批上时，批准或拒绝，然后让 agent 接着跑，过程同样用 SSE 推回去。

    req.approved：True 批准（按模型给的参数执行工具）/ False 拒绝（不执行，理由交给模型，模型据此回复用户）
    req.reason  ：拒绝理由，可以不填

    【它和命令行版的关系】就是 CustomerServiceSession.resume() 的网页版：
        命令行：session.resume(approved, reason) → agent.stream(Command(resume=...))
        网页  ：本接口                            → agent.astream_events(Command(resume=...), version="v3")
    Command(resume=值)：从上次 interrupt（暂停）的地方继续，这个值就是 interrupt 的「返回值」，
        HumanInTheLoopMiddleware 收到 {"decisions": [...]} 后，决定执行还是拒绝每个待审批的工具调用。

    【开始前的检查】和 _prepare 一样分两步，都在开始推流之前，失败照常返回 4xx：
        ① 必须是自己的对话（不存在 404、别人的 403）
        ② 必须真的停在审批上（409）：重复点击、两个页面同时点，第二次就会走到这里
    """
    thread_id = req.thread_id
    await check_thread_owner(threads, thread_id, user)
    config = {"configurable": {"thread_id": thread_id}}
    pending = _pending_approvals(await agent.aget_state(config))
    if not pending:
        raise HTTPException(status_code=409, detail="这段对话没有等待审批的操作（可能已经处理过了）")

    # decisions 的数量和顺序必须和待审批的操作一一对应：模型一次请求了两个要审批的工具，就要给两个决定。
    # 这里和命令行版一样，对所有待审批操作做同一个决定（页面上也只有一组按钮）
    if req.approved:
        decisions = [{"type": "approve"} for _ in pending]
    else:
        decisions = [{"type": "reject", "message": req.reason or "审核未通过，这个操作不执行"} for _ in pending]
    logger.info(f"[网页] {user.user_name} {'批准' if req.approved else '拒绝'}了 {[p.name for p in pending]}（thread_id={thread_id}）")

    # 【阶段 4】审批之后的过程，接着写在「停在审批上的那条客服消息」里（页面上也是同一个气泡）
    #   pending 以存档里的为准（刚才查出来的），消息表里的只是当时的显示
    last = await messages.last_assistant(thread_id)
    message_id, base = last if last else (None, empty_message())
    base["pending"] = [p.model_dump() for p in pending]
    return _sse_response(
        agent, Command(resume={"decisions": decisions}), thread_id, config, user,
        recorder=TurnRecorder.resume(base, req.approved, req.reason), threads=threads, messages=messages,
        message_id=message_id,
    )


def _sse_response(
    agent,
    inputs,
    thread_id: str,
    config: dict,
    user: UserContext,
    *,
    recorder: TurnRecorder,
    threads: ThreadRepository,
    messages: MessageRepository,
    message_id: int | None = None,
) -> StreamingResponse:
    """
    【阶段 3 从 chat_stream 里抽出来】跑一轮 agent，把事件用 SSE 推给浏览器。
    「发新消息」和「审批后继续」只有输入不同，后面的推流、收尾、错误处理完全一样：
        inputs = {"messages": [HumanMessage(...)]}   发新消息（chat_stream）
        inputs = Command(resume={"decisions": [...]}) 审批后继续（chat_resume）
    【阶段 4】推给浏览器的每条事件也交给 recorder 记一份；这一轮结束时把记好的客服消息存进消息表：
        message_id = None → 新加一条（发新消息）；有值 → 改那一条（审批后继续）
    * 后面的参数必须写成 recorder=... 这种「关键字」形式：参数多了，按位置传容易传错顺序
    返回：StreamingResponse（调用方直接 return 给 FastAPI）
    """

    def emit(event: str, data: dict) -> str:
        """【阶段 4】记一份，再编码成 SSE 文本（原来直接调 protocol.encode_sse 的地方都换成了它）"""
        recorder.apply(event, data)
        return protocol.encode_sse(event, data)

    async def events():
        """
        真正产生 SSE 文本的异步生成器。StreamingResponse 每从这里取到一段字符串，就立刻写给浏览器。
        为什么写成函数里的函数：它要用到外面的 inputs、user、agent、thread_id、config（闭包），不用再传一遍参数。
        """
        yield emit(protocol.RUN_STARTED, {"thread_id": thread_id})
        try:
            # ③ 边跑边推：runner 每翻译出一条事件，这里编码成 SSE 文本交给 StreamingResponse
            async for event, data in stream_agent(agent, inputs, config, user):
                yield emit(event, data)

            # ④ 跑完后读快照，整理出和 chat() 一模一样的结果，放进 done 事件
            #   为什么流都推完了还要发一份完整结果：
            #     a. return_direct 的工具（get_ticket_status）结果直接当回答，模型不再说话，流里没有这段文字的 token
            #     b. 前端以 done 为准校正最终显示（比如流里中途丢了片段），也拿到 token 统计
            snapshot = await agent.aget_state(config)
            result = _build_response(thread_id, snapshot)
            if result.pending_approvals:
                yield emit(
                    protocol.APPROVAL_REQUIRED,
                    {"pending": [p.model_dump() for p in result.pending_approvals]},
                )
            status = "interrupted" if result.pending_approvals else "completed"
            # model_dump()：Pydantic 对象 → 普通字典，才能转成 JSON
            yield emit(protocol.DONE, {"status": status, **result.model_dump()})
        except ModelError as e:
            logger.error(f"[网页] 流式运行时模型调用失败：{type(e).__name__}: {e}")
            # 复用阶段 1 的分类：只取给用户看的 detail，状态码在流里已经没用了
            yield emit(protocol.ERROR, {"message": model_error_to_http(e).detail})
            yield emit(protocol.DONE, {"status": "error", "thread_id": thread_id})
        except Exception as e:
            # 其他意外错误：细节写日志，前端只显示通用提示。
            # 注意：只捕获 Exception。浏览器断开时这里收到的是 asyncio.CancelledError（不属于 Exception），
            #   要让它继续往外抛，runner 里的 finally 才会执行 abort()，StreamingResponse 也才能正常收尾。
            logger.error(f"[网页] 流式运行出错：{type(e).__name__}: {e}", exc_info=e)
            yield emit(protocol.ERROR, {"message": "系统出错了，请稍后再试"})
            yield emit(protocol.DONE, {"status": "error", "thread_id": thread_id})
        finally:
            # 【阶段 4】不管这一轮怎么结束（正常 / 出错 / 点了停止），都把这条客服消息存进消息表
            if not recorder.finished:
                recorder.mark_stopped()  # 没收到 done 就离开 = 被停止或浏览器断开
            # anyio.CancelScope(shield=True)：「护盾」，里面的几步不受外面的取消影响，一定会执行完。
            #   为什么需要（实测）：点了停止时，Starlette 是用 anyio 的「取消范围」取消这个生成器的。
            #   去掉护盾试过：INSERT 执行了，但紧接着的 commit() 被取消掉 —— 这条连接上留下一个没提交的写事务，
            #   整个 app.db 被它锁住，下一句话 checkpointer 写存档时报 sqlite3.OperationalError: database is locked。
            #   套上护盾后，同样的停止操作，消息正常提交，下一句也正常回答。
            with anyio.CancelScope(shield=True):
                if message_id is None:
                    await messages.add(thread_id, "assistant", recorder.message)
                else:
                    await messages.update(message_id, recorder.message)
                await threads.touch(thread_id)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",  # 告诉浏览器：这是 SSE，一条条读
        headers={
            # no-cache：不要缓存这个响应（每次提问的结果都不一样）
            "Cache-Control": "no-cache",
            # 关掉 Nginx 之类反向代理的缓冲：不然代理会把事件攒成一大块再发，页面就又变成「一次性出来」了
            # 现在开发时没有 Nginx，留着是为了以后部署时不踩坑（真实项目的 SSE 接口基本都会带）
            "X-Accel-Buffering": "no",
        },
    )


async def _prepare(req: ChatRequest, user: UserContext, agent, threads: ThreadRepository) -> tuple[str, dict]:
    """
    【阶段 2 从 chat() 里抽出来】两个对话接口共用的「开始前检查」，返回 (thread_id, config)。

    ① 确定 thread_id：没传就开新对话；传了就查会话表，检查是不是这个用户自己的（不存在 404、别人的 403）
    ② 停在审批上的对话不能接着发新消息（→ 409），要先在审批卡片上批准或拒绝（POST /api/chat/resume）
       原因：上一条 AIMessage 请求了工具、但工具还没执行，消息链里缺 ToolMessage；
       这时再发新消息，下次调用模型会被 DeepSeek 拒绝（400：tool_calls 没有对应的 tool 消息）。
    ③ 【阶段 3】上一轮被「停止」按钮打断的，先把存档补完整（见 _close_stopped_run）
    ④ 【阶段 4】新对话：检查都通过后，在会话表里建一行（标题 = 这句话的前 30 个字）
    为什么抽出来：两个接口的检查必须完全一致，写两份迟早会改了一处忘了另一处。
    """
    is_new = req.thread_id is None
    if is_new:
        thread_id = _new_thread_id(user.user_id)
    else:
        thread_id = req.thread_id
        await check_thread_owner(threads, thread_id, user)
    # config 是 LangGraph 的运行配置，thread_id 必须放在 "configurable" 里（和命令行版一样）
    config = {"configurable": {"thread_id": thread_id}}

    # aget_state：get_state 的异步版，从 checkpointer 读这个 thread 的最新快照
    snapshot = await agent.aget_state(config)
    if _pending_approvals(snapshot):
        raise HTTPException(
            status_code=409,
            detail="这段对话有一个操作在等审批，请先在上面的审批卡片里批准或拒绝。",
        )
    await _close_stopped_run(agent, config, snapshot)

    if is_new:
        await threads.create(thread_id, user.user_id, req.message)
    logger.info(f"[网页] {user.user_name} 提问（thread_id={thread_id}）：{req.message}")
    return thread_id, config


async def _close_stopped_run(agent, config: dict, snapshot) -> None:
    """
    【阶段 3】上一轮被「停止」按钮打断时，把存档补完整，否则这段对话再也问不下去。

    【为什么会坏】（webapp/backend/runtime/stop_probe.py 实测）
        停止 = 浏览器断开 → runner.py 的 finally 里 run.abort()，图停在半路。checkpointer 里留下的是「最后一个走完的节点」的存档：
        ① 停在模型生成文字时：存档里只有用户那句 HumanMessage → 没问题，下一句直接接上（连续两条 HumanMessage 模型能接受）
        ② 停在工具执行时：存档里有一条「请求调用工具」的 AIMessage，但没有对应的 ToolMessage（工具结果还没写进去）
           → 下一句发出去，DeepSeek 直接报 400：
             An assistant message with 'tool_calls' must be followed by tool messages responding to each 'tool_call_id'
    【怎么补】给每个没有结果的工具调用补一条 ToolMessage，告诉模型「用户中途停止了」。补上之后实测 DeepSeek 正常回答。
        补在这里（下一次请求开始前）而不是停止的那一刻：停止时请求已经被取消了，再做异步操作不可靠；
        下一次请求一定会经过这里，存档一定会被补好。
    注意（实测）：停止只能取消 asyncio 里的等待，已经在线程里跑起来的同步工具（search_knowledge 连 Chroma）会跑完，
        只是结果被丢掉。所以补的文字写「没有拿到结果」，而不是「没有执行」—— 工具可能已经执行了。

    snapshot.next：图下一步要执行的节点。正常跑完是空的；停在半路或停在审批上时不为空（停在审批上的情况调用前已经拦掉了）
    """
    if not snapshot.next:
        return
    messages = snapshot.values.get("messages", [])
    # 已经有结果的工具调用 id
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    # 最后一条 AIMessage 里，还没有结果的工具调用
    last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    missing = [c for c in (last_ai.tool_calls if last_ai else []) if c["id"] not in answered]
    if not missing:
        return
    patch = [
        ToolMessage(
            content="用户中途点了停止，没有拿到这个工具的结果。如果用户还需要，请重新调用。",
            tool_call_id=c["id"],
            name=c["name"],
            status="error",
        )
        for c in missing
    ]
    # aupdate_state：直接往存档里写一次更新，效果和「tools 节点执行完、返回了这些 ToolMessage」一样
    #   as_node="tools"：以 tools 节点的名义写（create_agent 里执行工具的节点就叫 tools）
    await agent.aupdate_state(config, {"messages": patch}, as_node="tools")
    logger.info(f"[网页] 上一轮被停止，补了 {len(patch)} 条工具结果：{[c['name'] for c in missing]}")


def _new_thread_id(user_id: str) -> str:
    """生成新的 thread_id：<user_id>-<8 位随机十六进制>，例如 U1001-26bb34ba（格式和命令行版一致）"""
    return f"{user_id}-{uuid.uuid4().hex[:8]}"


def _pending_approvals(snapshot) -> list[ToolCallInfo]:
    """
    从快照里取出待审批的操作（和命令行版 CustomerServiceSession.pending_approvals 同一个逻辑）。
    snapshot.tasks：下一步要执行的任务；停在审批上时，任务里带着 HumanInTheLoopMiddleware 抛出的 interrupt
    intr.value["action_requests"]：每个待审批的工具调用 {"name", "args", "description"}
    返回：ToolCallInfo 列表；没停在审批上时是空列表
    """
    pending = []
    for task in snapshot.tasks:
        for intr in task.interrupts:
            for r in intr.value.get("action_requests", []):
                pending.append(ToolCallInfo(name=r["name"], args=r["args"]))
    return pending


def _build_response(thread_id: str, snapshot) -> ChatResponse:
    """
    把 agent 跑完后的快照整理成前端要的 ChatResponse。
    snapshot.values：最终 State，messages 是整段对话的全部消息（包括以前几轮的）
    """
    messages = snapshot.values.get("messages", [])

    # 只看「这一轮」：最后一条 HumanMessage 之后的消息就是这一轮新产生的
    last_human = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
    this_turn = messages[last_human + 1:]

    tool_calls, sources = [], []
    for m in this_turn:
        if isinstance(m, AIMessage):
            tool_calls += [ToolCallInfo(name=c["name"], args=c["args"]) for c in m.tool_calls]
        elif isinstance(m, ToolMessage) and m.name == "search_knowledge" and m.artifact:
            # artifact：search_knowledge 返回的 hits（模型看不到），取出处文件名给页面显示「参考资料」
            # 注意：不能写成 sources += [h["source"] for h in m.artifact if h["source"] not in sources]
            #   列表推导式里的 sources 是「加之前」的旧列表，同一次检索命中同一文件的两个片段时会重复。
            #   实测「回不了充电座」返回过两次「扫地机器人100问2.txt」，前端用文件名当 React key 还会报警告。
            for h in m.artifact:
                if h["source"] not in sources:
                    sources.append(h["source"])

    pending = _pending_approvals(snapshot)
    answer = ""
    if this_turn:
        last = this_turn[-1]
        if isinstance(last, AIMessage):
            # .text：只取文字部分（content 有时是列表，.text 会把文字拼好）
            # 停在审批上时，最后一条是「请求工具」的 AIMessage，文字通常是空的
            answer = last.text
        elif isinstance(last, ToolMessage) and not pending:
            # return_direct 的工具：工具结果直接当最终回答（和命令行版 _run 最后的 "final" 事件一样）
            answer = str(last.content)

    return ChatResponse(
        thread_id=thread_id,
        answer=answer,
        tool_calls=tool_calls,
        sources=sources,
        pending_approvals=pending,
        token_usage=snapshot.values.get("token_usage"),
    )
