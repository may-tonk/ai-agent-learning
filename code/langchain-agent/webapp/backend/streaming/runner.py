"""
【v2 网页版新增 · 阶段 2】跑 agent 的事件流，把 LangChain 原始事件翻译成前端事件（protocol.py）

【在整体流程里的位置】
    routers/chat.py 的 POST /api/chat/stream
      → 本文件 stream_agent()：await agent.astream_events(..., version="v3") → async for 原始事件
      → 翻译成 (事件名, 数据) 一条条交回去 → chat.py 编码成 SSE → 浏览器
    写法就是 lessons/06 第 4、6 节学过的「原始协议事件」，这里只是把 print 换成了 yield。

【只翻译这几种原始事件，其余丢掉】
    原始事件 method="messages"，节点是 model：
        message-start                         → 不发，只把 call（第几次模型调用）加 1
        content-block-delta 且 type=text-delta → token {text, call}
        一整条 AIMessage（模型不流式时）       → call 加 1，整段文字作为一个 token
    原始事件 method="tools"：
        tool-started   → tool_started  {id, name, args}
        tool-finished  → tool_finished {id, name, ok, sources}
        tool-error     → tool_finished {id, name, ok=False, sources=[]}
    原始事件 method="custom"（阶段 6）：工具里 get_stream_writer() 写的数据
        带 tool_call_id 的 → tool_progress {id, step, status, message}
    其余（values 整份 State、tool-output-delta、别的节点的消息…）都不发给前端。

【为什么只要 model 节点的文字】
    build_agent() 里的 SummarizationMiddleware 在对话太长时，会在 before_model 节点里调一次模型写「摘要」，
    那次调用的文字也会出现在 messages 事件里，但它不是给用户的回答。按 meta["langgraph_node"] == "model" 过滤掉。

【为什么 token 要带 call】
    一轮里模型可能被调用好几次：第 1 次决定调工具（DeepSeek 有时会先说一句「我帮您查一下」），
    工具跑完第 2 次才给出最终回答。前端看到 call 变了，就知道上一段文字不是最终回答，把显示区清空重新开始。
    这样最后留在页面上的，正好是最后一次调用的文字 = done 里的 answer。

谁用它：routers/chat.py
"""
import warnings
from collections.abc import AsyncIterator

from langchain.messages import ToolMessage
from langchain_core._api import LangChainBetaWarning
from langchain_core.messages import BaseMessage
from langgraph.stream import CustomTransformer
from langgraph.types import Command

from utils.logger_handler import logger
from webapp.backend.streaming import protocol

# v3 在 langgraph 1.2.16 里标注为实验性接口，每次调用都会打一条 LangChainBetaWarning（lessons/06 讲过）。
# 已经知道了，关掉，免得每次提问都在后端日志里刷一条。升级 langgraph 后如果 v3 转正，这行可以删掉。
warnings.filterwarnings("ignore", category=LangChainBetaWarning)


async def stream_agent(agent, inputs, config: dict, context) -> AsyncIterator[tuple[str, dict]]:
    """
    跑一轮 agent，边跑边产出前端事件。

    agent：build_agent() 建好的 agent
    inputs：{"messages": [HumanMessage(...)]}；审批后继续时是 Command(resume={"decisions": [...]})（阶段 3，见 chat.py 的 chat_resume）
    config：{"configurable": {"thread_id": ...}}
    context：当前用户 UserContext
    产出：(事件名, 数据) —— 事件名是 protocol 里的常量
    异常：模型出错（ModelError 等）会原样抛出，由 chat.py 转成 error 事件；本函数不吞异常

    这是一个「异步生成器」（async def 里有 yield）：调用方用 async for 一条条取，
    取一条才往下跑一点，所以 DeepSeek 吐出一个字，浏览器几乎同时就能收到。
    """
    # 坑（lessons/06 第 6 节）：异步版要先 await 才能拿到流对象，不能直接 async for
    # 【阶段 6】transformers=[CustomTransformer]：让 v3 事件流里带上 custom 事件（工具用 get_stream_writer 写的数据）。
    #   实测（webapp/backend/runtime/p6_probe.py）：不加这个参数，工具里写的东西根本不会出现在事件流里（默认没订阅 custom）；
    #   加上以后，custom 事件出现在 tool-started 和 tool-finished 之间，data 就是工具写的那个字典，原样到达。
    run = await agent.astream_events(inputs, config, context=context, version="v3", transformers=[CustomTransformer])
    finished = False    # 是否正常读到了最后一条事件
    call = 0            # 这一轮第几次模型调用
    tool_names = {}     # tool_call_id → 工具名。tool-finished 事件里没有工具名（lessons/06 实测），要靠开始时记下来
    try:
        async for ev in run:
            method, data = ev["method"], ev["params"]["data"]

            if method == "messages":
                payload, meta = data  # messages 事件的 data 是 (片段事件, 元数据)
                if meta.get("langgraph_node") != "model":
                    continue
                if isinstance(payload, BaseMessage):
                    # 注意（实测）：模型「不支持流式」时，这里拿到的不是片段事件，而是一整条消息（AIMessage）。
                    #   langgraph 只在模型真正逐字吐出时发 message-start / content-block-delta；
                    #   不流式的模型（例如测试用的假模型 tests/fakes.py）跑完后，把整条消息作为一条事件补发出来。
                    #   当成「一次调用、一次性给出全部文字」处理，前端看到的就是一整段 token。
                    call += 1
                    if payload.text:
                        yield protocol.TOKEN, {"text": payload.text, "call": call}
                elif payload["event"] == "message-start":
                    call += 1
                elif payload["event"] == "content-block-delta" and payload["delta"].get("type") == "text-delta":
                    text = payload["delta"]["text"]
                    if text:  # 空片段没必要发
                        yield protocol.TOKEN, {"text": text, "call": call}

            elif method == "tools":
                call_id = data["tool_call_id"]
                if data["event"] == "tool-started":
                    tool_names[call_id] = data["tool_name"]
                    yield protocol.TOOL_STARTED, {
                        "id": call_id,
                        "name": data["tool_name"],
                        "args": data.get("input") or {},
                    }
                elif data["event"] == "tool-finished":
                    msg = _tool_message(data["output"])
                    yield protocol.TOOL_FINISHED, {
                        "id": call_id,
                        "name": tool_names.get(call_id, ""),
                        # status="error"：工具抛了异常，被 ToolCallGuard 中间件转成了一条错误消息（见 agent/middleware.py 第 4 节）
                        "ok": msg is None or msg.status != "error",
                        "sources": _sources(msg),
                    }
                elif data["event"] == "tool-error":
                    # 工具本身抛了异常。data["message"] 是原始异常文字（可能带内部细节），不发给前端；
                    # 给模型和用户看的提示由 ToolCallGuard 生成，会出现在后面模型的回答里
                    yield protocol.TOOL_FINISHED, {"id": call_id, "name": tool_names.get(call_id, ""), "ok": False, "sources": []}

            elif method == "custom":
                # 【阶段 6】工具写进来的进度。custom 流里的数据格式完全由我们自己定（框架不检查），
                #   所以先确认是不是我们约定的那种（带 tool_call_id 的字典），别的自定义数据不转发
                if isinstance(data, dict) and data.get("tool_call_id"):
                    yield protocol.TOOL_PROGRESS, {
                        "id": data["tool_call_id"],
                        "step": data.get("step", ""),
                        "status": data.get("status", "done"),
                        "message": data.get("message", ""),
                    }
        finished = True
    finally:
        # 没正常读完就离开了这里：浏览器断开（StreamingResponse 会取消这个生成器）、或者翻译时出了错。
        # 这时要明确告诉框架「这次运行取消」，正在进行的模型调用也会被停掉，不再白白花 token（lessons/06 第 6 节）。
        # 写在 finally 里：不管哪种原因离开，都一定会执行。
        if not finished:
            logger.info("[流式] 没有正常读完（浏览器断开 / 点了停止 / 出错），取消这次运行")
            await run.abort()
            logger.info("[流式] 已取消")


def _tool_message(output) -> ToolMessage | None:
    """
    从 tool-finished 的 output 里取出 ToolMessage。
    一般工具：output 就是 ToolMessage（lessons/06 实测）
    返回 Command 的工具（例如 get_order_detail，要顺便更新 State）：ToolMessage 在 Command.update["messages"] 里
    都找不到时返回 None
    """
    if isinstance(output, ToolMessage):
        return output
    if isinstance(output, Command) and isinstance(output.update, dict):
        for m in output.update.get("messages", []):
            if isinstance(m, ToolMessage):
                return m
    return None


def _sources(msg: ToolMessage | None) -> list[str]:
    """知识库工具的参考资料文件名（去重、保持顺序）。和 chat.py 的 _build_response 取法一样：来自 search_knowledge 的 artifact"""
    if msg is None or msg.name != "search_knowledge" or not msg.artifact:
        return []
    sources = []
    for h in msg.artifact:
        if h["source"] not in sources:
            sources.append(h["source"])
    return sources
