"""
【v2 网页版新增 · 阶段 0】stream_events 和 astream_events：事件流（v2 原始事件 vs v3 分类视图）

要回答的问题：
    stream_events 和 lessons/05 的 stream 有什么不同？v2 和 v3 又有什么不同？
    v3 的 messages、tool_calls、custom、output、interrupts 这些「视图」分别给什么？
    想按真实发生顺序同时看「模型的字」和「工具的执行」，怎么写（interleave）？
    最底层的「原始协议事件」长什么样？网页后端为什么要直接读它？
    审批中断在 v3 里怎么表现、怎么继续？
    异步写法有哪些和同步不一样的坑？用户点「停止」时怎么让 agent 真的停下来（abort）？

【和 lessons/05 的关系】
    05 的 stream(stream_mode=...)：你选模式，拿到的是「(模式, 数据)」，不同模式的数据格式各不相同，要自己拆
    本文件的 stream_events(version="v3")：框架把一次运行拆成几类「视图」，每类都是有名字、有字段的对象
    v2 是旧的事件流接口：一条条回调事件（on_chat_model_stream、on_tool_start…），要自己按事件名过滤

【在整体流程里的位置】
    网页版后端 webapp/backend/streaming/runner.py（阶段 2）= 本文件第 6 节的写法：
    astream_events(version="v3") → 逐条读原始协议事件（第 4 节）→ 翻译成前端事件 → SSE 推给浏览器

需要：DEEPSEEK_API_KEY（不需要 Chroma）
运行：python lessons/06_event_streaming.py [--part N]
注意：v3 在当前版本（langgraph 1.2.16）标注为实验性接口，运行时会打印 LangChainBetaWarning，属于正常现象。
"""
import _common  # noqa: F401
from _common import note, run_parts, title

import asyncio
import time
import warnings
from collections import Counter

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.messages import HumanMessage
from langchain.tools import tool
from langchain_core._api import LangChainBetaWarning
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from langgraph.stream.transformers import CustomTransformer
from langgraph.types import Command

from agent.state import UserContext
from agent.tools import list_my_orders
from model.factory import build_chat_model

# v3 每次调用都会打印一次「实验性接口」警告，已经知道了，这里关掉，免得刷屏
warnings.filterwarnings("ignore", category=LangChainBetaWarning)

ZHANG = UserContext(user_id="U1001", user_name="张三", role="customer")
ASK_ORDERS = {"messages": [HumanMessage("我有哪些订单？")]}
ASK_DIAGNOSE = {"messages": [HumanMessage("帮我给订单 SO20260312 的机器做个远程诊断")]}
ASK_RESET = {"messages": [HumanMessage("我的订单 SO20260312 那台机器乱了，帮我远程恢复出厂设置")]}


class Clock:
    """计时器：返回「距离开始过了多少毫秒」（和 lessons/05 一样）"""

    def __init__(self):
        self.start = time.perf_counter()

    def ms(self) -> str:
        return f"[{(time.perf_counter() - self.start) * 1000:6.0f} ms]"


def cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": f"lesson6-{thread_id}"}}


@tool
def diagnose_device(order_id: str) -> str:
    """对用户订单里的扫地机器人做一次远程诊断（检查传感器、电池、固件）。用户要求「远程诊断」「检测一下机器」时调用。"""
    # 和 lessons/05 第 5 节同一个演示工具：每完成一步用 writer 推一条自定义进度
    writer = get_stream_writer()
    for step in ("连接设备", "检查传感器", "检查电池", "检查固件"):
        writer({"order_id": order_id, "step": step})
        time.sleep(0.5)
    return f"订单 {order_id} 的设备诊断完成：传感器正常，电池健康度 92%，固件已是最新版本。"


@tool
def reset_device(order_id: str) -> str:
    """远程把用户订单里的扫地机器人恢复出厂设置（会清除地图和清扫记录）。用户明确要求恢复出厂设置时调用。"""
    # 第 5 节演示审批用：这种不可撤销的操作，真实项目里必须人工确认后才执行
    return f"订单 {order_id} 的设备已恢复出厂设置，请在 App 里重新配网和建图。"


def lesson_agent(approval: bool = False):
    """
    本课专用的小 agent：真实模型 + 订单工具 + 两个演示工具。
    approval=True 时加上 HumanInTheLoopMiddleware：reset_device 执行前暂停，等人工批准（第 5 节）。
    不用 build_agent() 的原因同 lessons/05：写这课时 build_agent() 有 2 个自定义中间件只有同步版本，异步会报错。
    【v2 网页版】阶段 1 已补上异步版本；这里继续用小 agent，是为了事件输出简单，只看事件流本身。
    """
    middleware = []
    if approval:
        middleware.append(HumanInTheLoopMiddleware(interrupt_on={"reset_device": {"allowed_decisions": ["approve", "reject"]}}))
    return create_agent(
        # 注意（实测踩坑）：这里不用 get_chat_model()，而是每次 build_chat_model() 新建一个模型对象。
        #   get_chat_model() 带 @lru_cache，整个进程共用一个模型对象，它里面的「异步 HTTP 连接池」
        #   会绑定在第一次使用它的那个事件循环上。本文件第 1 节和第 6 节各自 asyncio.run() 一次，
        #   每次 asyncio.run 都会新建一个事件循环、用完就关掉；第 6 节复用第 1 节留下的连接时就报
        #   RuntimeError: Event loop is closed
        #   网页后端不会遇到：uvicorn 整个进程只有一个事件循环，从启动到关闭一直是它，共用模型对象反而更省。
        #   结论：一个进程里只开一个事件循环（真实项目都是这样）；写练习脚本多次 asyncio.run 时，模型对象别跨循环复用。
        model=build_chat_model("chat"),
        tools=[list_my_orders, diagnose_device, reset_device],
        system_prompt="你是扫地机器人售后客服，回答简洁，不超过 80 字。用户的身份由系统提供，不要向用户索要。",
        context_schema=UserContext,
        checkpointer=InMemorySaver(),  # 第 5 节的审批中断必须有 checkpointer，暂停时的 State 存在这里
        middleware=middleware,
    )


def part1_v2_raw_callbacks():
    title("1. v2：一条条「回调事件」，要自己按事件名过滤")
    agent = lesson_agent()
    clock = Clock()
    counter = Counter()  # 统计每种事件出现了多少次

    # 注意（实测）：v2 只有异步版。写 agent.stream_events(..., version="v2") 会直接报
    #   NotImplementedError: stream_events(version='v2') is not supported. Use astream_events() for v1/v2
    # 所以这里套一个 async 函数，用 astream_events；同步的 stream_events 只支持 v3（第 2~5 节）
    async def main():
        first_token_printed = False
        # astream_events(input, config, version="v2")：v2 不用 await，直接 async for，每条是一个字典
        #   （v3 的异步版要先 await 拿到流对象，见第 6 节，这是两个版本写法上的一个区别）
        #   ev["event"]  事件名，格式是 on_<对象类型>_<start|stream|end>
        #   ev["name"]   是谁产生的（模型类名、工具名、节点名、中间件名）
        #   ev["data"]   内容：stream 事件里是 chunk，start 事件里是 input，end 事件里是 output
        async for ev in agent.astream_events(ASK_ORDERS, cfg("p1"), context=ZHANG, version="v2"):
            counter[ev["event"]] += 1
            if ev["event"] == "on_chat_model_start":
                first_token_printed = False
                print(f"{clock.ms()} on_chat_model_start   模型开始一次调用")
            elif ev["event"] == "on_chat_model_stream" and ev["data"]["chunk"].text and not first_token_printed:
                first_token_printed = True
                print(f"{clock.ms()} on_chat_model_stream  第一个字：{ev['data']['chunk'].text!r}（之后还有很多条，省略）")
            elif ev["event"] in ("on_tool_start", "on_tool_end"):
                print(f"{clock.ms()} {ev['event']:<21} 工具 {ev['name']}")

    asyncio.run(main())
    print(f"\n这一轮一共 {sum(counter.values())} 条事件，按类型：")
    for name, count in counter.most_common():
        print(f"  {name:<24} {count}")
    note("v2 把运行过程中「每个对象的开始、流式片段、结束」都报出来：图、每个节点、模型、工具……")
    note("实测这一轮约 130 条（每次略有不同）：100 多条是模型的逐字片段，14 条 on_chain_*（图和节点的开始/结束）前端根本不关心。")
    note("麻烦在于全是平铺的一条条字典：哪段字属于哪次模型调用、工具开始和结束怎么配对，都要自己按 event、name、run_id 去拼。")
    note("这就是 v3 要解决的问题：框架先替你分好类、配好对。")


def part2_v3_messages():
    title("2. v3 的 messages 视图：每次模型调用是一个对象，文字在它的 .text 里流出来")
    agent = lesson_agent()
    clock = Clock()
    # version="v3"：返回 GraphRunStream 对象（不是生成器），上面挂着几个「视图」：
    #   run.messages   每次模型调用一个 ChatModelStream
    #   run.values     每一步之后的完整 State（相当于 05 的 values 模式）
    #   run.tool_calls 每次工具执行一个 ToolCallStream（第 3 节）
    #   run.output     整轮结束后的最终 State
    run = agent.stream_events(ASK_ORDERS, cfg("p2"), context=ZHANG, version="v3")
    for i, model_call in enumerate(run.messages, start=1):
        # model_call.node：哪个节点产生的（create_agent 里模型节点叫 model）
        print(f"{clock.ms()} 第 {i} 次模型调用开始（节点 {model_call.node}）")
        pieces = 0
        for delta in model_call.text:  # 第二层循环：这一次调用的文字增量，一段一段到达
            pieces += 1
            if pieces <= 3:
                print(f"{clock.ms()}     文字增量：{delta!r}")
        full = model_call.output  # 这次调用结束后的完整 AIMessage
        print(f"{clock.ms()}     结束：{pieces} 段文字，请求工具 {[c['name'] for c in full.tool_calls]}，"
              f"token {full.usage_metadata}")
    final_state = run.output  # 访问 output 时如果还没跑完，会先把剩下的跑完
    print(f"\n最终回答：{final_state['messages'][-1].text[:120]}")
    note("两层循环：外层是「第几次模型调用」，内层是「这次调用的文字增量」。")
    note("第 1 次调用 0 段文字、请求了 list_my_orders：它只是决定调工具，不是给用户的回答，不要显示。")
    note("每次调用结束都能拿到完整消息和 token 用量（output.usage_metadata），前端的「本次消耗」就从这里来。")


def part3_v3_interleave():
    title("3. interleave：按真实发生顺序，同时看模型、工具、自定义进度")
    agent = lesson_agent()
    clock = Clock()
    # transformers=[CustomTransformer]：custom 视图默认不开，要用时显式注册（对应 05 的 custom 模式）
    run = agent.stream_events(ASK_DIAGNOSE, cfg("p3"), context=ZHANG, version="v3", transformers=[CustomTransformer])
    print("这次运行有哪些视图：", list(run.extensions))
    tool_handles = []
    # interleave(名字1, 名字2, ...)：把几个视图合成一条流，按到达先后给出 (视图名, 内容)
    # 不能写成先 for run.messages 再 for run.tool_calls：那样会先把模型的全部看完，顺序就乱了
    for name, item in run.interleave("messages", "tool_calls", "custom"):
        if name == "messages":
            text = "".join(item.text)  # 把这次调用的文字收齐（这里只看顺序，不逐字打印）
            print(f"{clock.ms()} messages   模型调用结束：{len(text)} 字，请求工具 {[c['name'] for c in item.output.tool_calls]}")
        elif name == "tool_calls":
            # ToolCallStream：工具「开始执行」时就给出这个对象，此时 completed=False、output=None
            # 它是一个「句柄」，工具执行完后 completed 和 output 才会被填上
            tool_handles.append(item)
            print(f"{clock.ms()} tool_calls 工具开始：{item.tool_name} 参数 {item.input}（id={item.tool_call_id[-6:]}）")
        else:
            print(f"{clock.ms()} custom     进度：{item}")
    for h in tool_handles:
        print(f"\n跑完后再看工具句柄：completed={h.completed} error={h.error} output={str(h.output)[:60]}")
    note("顺序：模型决定调工具 → 工具开始 → 4 条进度（工具执行中）→ 模型给出最终回答。网页上的「工具卡片」就按这个顺序变化。")
    note("tool_calls 的参数（item.input）是完整的、已经解析好的字典，不是 05 第 3 节那种半截 JSON。")
    note("interleave 只有同步版本有；异步版本要用第 4、6 节的「原始协议事件」，这也是网页后端选择它的原因。")


def part4_v3_protocol_events():
    title("4. 原始协议事件：直接 for 遍历 run，最底层、最完整的一条流")
    agent = lesson_agent()
    clock = Clock()
    counter = Counter()  # 按 method 统计事件条数
    text_count = 0       # 单独数文字片段，只打印前 2 条
    run = agent.stream_events(ASK_DIAGNOSE, cfg("p4"), context=ZHANG, version="v3", transformers=[CustomTransformer])
    # 每条事件是字典：{"method": 类别, "params": {"namespace": [...], "data": 内容, ...}}
    #   method="messages"  data 是 (片段事件, 元数据)。片段事件的 event 字段：
    #       message-start → content-block-start → content-block-delta（多次）→ content-block-finish → message-finish
    #       content-block-delta 里 delta.type == "text-delta" 是文字，"block-delta" 是工具调用参数片段
    #   method="tools"     data["event"] 是 tool-started（带 tool_call_id、tool_name、input）
    #                      或 tool-finished（只带 tool_call_id、output，output 是 ToolMessage）
    #   method="custom"    data 是工具里 writer(...) 写的内容
    #   method="values"    data 是当前完整 State；遇到审批中断时 params 里还有 interrupts
    for ev in run:
        method, data = ev["method"], ev["params"]["data"]
        counter[method] += 1
        if method == "messages":
            payload, meta = data
            if payload["event"] == "message-start":
                print(f"{clock.ms()} messages  message-start（节点 {meta['langgraph_node']}）")
            elif payload["event"] == "content-block-delta" and payload["delta"].get("type") == "text-delta":
                text_count += 1
                if text_count <= 2:
                    print(f"{clock.ms()} messages  text-delta {payload['delta']['text']!r}（之后的省略）")
            elif payload["event"] == "message-finish":
                print(f"{clock.ms()} messages  message-finish")
        elif method == "tools":
            # tool-started 带 tool_name 和 input；tool-finished 只带 tool_call_id 和 output（实测没有 tool_name），
            # 所以前端要靠 tool_call_id 把「开始」和「结束」配成一对，更新同一张工具卡片
            if data["event"] == "tool-started":
                print(f"{clock.ms()} tools     tool-started  {data['tool_name']} 参数 {data['input']}")
            else:
                # 实测 output 是一个 ToolMessage 对象（不是字符串），文字在它的 .content 里
                print(f"{clock.ms()} tools     {data['event']} 结果 {data['output'].content[:30]}…")
        elif method == "custom":
            print(f"{clock.ms()} custom    {data}")
        elif method == "values":
            print(f"{clock.ms()} values    State 快照：{len(data['messages'])} 条消息")
    print(f"\n事件数量：{dict(counter)}，其中文字片段 {text_count} 条")
    note("和 v2 比：实测这一轮约 55 条（每次略有不同），每条都有明确的类别（method），没有 on_chain_start 那类噪音；")
    note("  一次模型调用的片段被 message-start / message-finish 包起来，工具的开始和结束用 tool_call_id 配对，不用自己拼。")
    note("和 interleave 比：原始事件是一条流、天然按顺序、同步异步都能用，所以网页后端读它，再翻译成前端事件：")
    note("  text-delta → token；tool-started → tool_started；tool-finished → tool_finished；"
         "custom → retrieval_progress；values 里有 interrupts → approval_required；流结束 → done。")


def part5_v3_interrupt():
    title("5. 审批中断：v3 里怎么看出 agent 停下了，怎么继续")
    agent = lesson_agent(approval=True)
    config = cfg("p5")

    run = agent.stream_events(ASK_RESET, config, context=ZHANG, version="v3")
    for model_call in run.messages:  # 先把这一段跑完
        "".join(model_call.text)
    # run.interrupted：这一轮是不是停在了审批上；run.interrupts：停下的原因（可能有多个）
    print("interrupted =", run.interrupted)
    if not run.interrupted:
        print("模型这次没有直接调用 reset_device（可能在先确认信息），重新运行一次即可")
        return
    request = run.interrupts[0].value["action_requests"][0]
    print("等待审批：", request["name"], request["args"])

    print("\n客服点了【批准】→ 用 Command(resume=...) 继续同一个 thread")
    # resume 的格式由 HumanInTheLoopMiddleware 规定：decisions 列表，和 action_requests 一一对应
    run = agent.stream_events(Command(resume={"decisions": [{"type": "approve"}]}), config, context=ZHANG, version="v3")
    print("继续之后的回答：", run.output["messages"][-1].text)
    note("暂停时 State 存在 checkpointer 里；继续时传 Command(resume=...) 而不是新消息，thread_id 必须相同。")
    note("网页版：发现 interrupted → 给浏览器发 approval_required 事件并结束这次 SSE；用户点了批准 → 前端调 /api/chat/resume，"
         "后端执行这里的第二步，再开一次 SSE 把后续的字推回去。")


def part6_async_and_abort():
    title("6. 异步版 astream_events：网页后端的真实写法，以及用户点「停止」时怎么停")

    async def full_run():
        agent = lesson_agent()
        clock = Clock()
        # 坑 1：astream_events(...) 要先 await 才能拿到流对象（AsyncGraphRunStream），不能直接 async for
        run = await agent.astream_events(ASK_ORDERS, cfg("p6a"), context=ZHANG, version="v3")
        text = []
        async for ev in run:  # 异步版本没有 interleave，直接读原始协议事件（第 4 节）
            if ev["method"] == "messages":
                payload, meta = ev["params"]["data"]
                if (payload["event"] == "content-block-delta" and payload["delta"].get("type") == "text-delta"
                        and meta["langgraph_node"] == "model"):
                    text.append(payload["delta"]["text"])
        # 坑 2：同步版 run.output 是属性，异步版 run.output() 是要 await 的方法（interrupted、interrupts 也一样）
        state = await run.output()
        last = state["messages"][-1]
        print(f"{clock.ms()} 收到 {len(text)} 段文字，拼起来：{''.join(text)[:60]}…")
        # 坑 3：v3 跑完后，AIMessage.content 可能变成「内容块列表」，而不是字符串
        print(f"最后一条消息的 content 类型：{type(last.content).__name__}；用 .text 取文字永远是字符串：{last.text[:30]}…")

    async def stop_halfway():
        agent = lesson_agent()
        clock = Clock()
        run = await agent.astream_events(ASK_ORDERS, cfg("p6b"), context=ZHANG, version="v3")
        pieces = 0
        async for ev in run:
            if ev["method"] == "messages":
                payload, _ = ev["params"]["data"]
                if payload["event"] == "content-block-delta" and payload["delta"].get("type") == "text-delta":
                    pieces += 1
                    if pieces == 5:
                        # abort()：关闭底层的图运行（正在进行的模型调用会被取消），之后不会再有事件
                        await run.abort()
                        print(f"{clock.ms()} 收到第 5 段文字时模拟用户点了「停止」，调用 run.abort()")
                        break
        print(f"{clock.ms()} 已停止，后面没有再收到任何事件")
        # 为什么不能只写 break：break 只表示「我这边不读了」，底层的图运行什么时候被关掉不由你控制；
        # abort() 是明确告诉框架「这次运行取消」。网页后端必须显式调用它，不能指望 Python 自己回收。

    async def main():
        await full_run()
        print()
        await stop_halfway()

    # 两个演示放进同一个 asyncio.run（同一个事件循环）里跑，和网页后端「一个进程一个循环」的情况一致。
    # 分成两次 asyncio.run 也能跑，但第一个循环关掉后，留在它上面的 HTTP 连接被回收时
    # 偶尔会打印一段 Task exception was never retrieved ... Event loop is closed（实测出现过，不影响结果）
    asyncio.run(main())
    note("网页后端就是 full_run 的写法：await astream_events → async for 原始事件 → 翻译 → 推给浏览器。")
    note("浏览器断开或点停止时，后端要调用 abort()，而且要在 finally 里调用，保证任何情况下都会执行。阶段 3 实现。")


if __name__ == "__main__":
    run_parts(
        {
            1: part1_v2_raw_callbacks,
            2: part2_v3_messages,
            3: part3_v3_interleave,
            4: part4_v3_protocol_events,
            5: part5_v3_interrupt,
            6: part6_async_and_abort,
        },
        "stream_events / astream_events 练习",
    )
