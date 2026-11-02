"""
【v2 网页版新增 · 阶段 0】stream 和 astream：Agent 内部的「流」到底是什么

要回答的问题：
    invoke 和 stream 差在哪？「流式」到底快在哪里（首字时间 vs 全部结束的时间）？
    stream_mode 的 values / updates / messages 各给什么？同时订阅多种模式时数据长什么样？
    messages 模式里为什么还会出现 ToolMessage？怎么只拿「模型对用户说的话」？
    工具执行很久时，怎么把进度推出去（custom 模式 + get_stream_writer）？
    astream 和 stream 有什么区别？网页后端（FastAPI）为什么一定要用异步？
    为什么现在的 build_agent() 一用异步就报错？（阶段 1 要修的问题）

和 lessons/04 第 2 节的关系：04 只是「看一眼」三种模式；这里给每条数据打上毫秒时间戳逐个拆开，
再补上 custom、多模式、astream 和并发。

【在整体流程里的位置】
    命令行版 agent/agent.py 的 CustomerServiceSession._run() 用的就是本文件第 4 节的写法（stream + 多模式）
    网页版后端（阶段 2）用的是 lessons/06 的 astream_events v3；本文件是它的基础

需要：DEEPSEEK_API_KEY（不需要 Chroma：只问订单问题，不查知识库）
运行：python lessons/05_stream_modes.py [--part N]
注意：毫秒数每次都不一样，重点看「先后顺序」，以及「第一个字」和「全部结束」之间差了多少
"""
import _common  # noqa: F401
from _common import note, run_parts, title

import asyncio
import time

from langchain.agents import create_agent
from langchain.messages import HumanMessage, ToolMessage
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer

from agent.agent import build_agent
from agent.state import UserContext
from agent.tools import check_warranty, list_my_orders
from model.factory import get_chat_model

ZHANG = UserContext(user_id="U1001", user_name="张三", role="customer")
LI = UserContext(user_id="U1002", user_name="李四", role="customer")
QUESTION = "我有哪些订单？"


class Clock:
    """
    计时器：每次调用 ms() 返回「距离开始过了多少毫秒」。
    为什么要它：流式和非流式最后拿到的内容一样，区别全在「什么时候拿到」，不打时间戳根本看不出来。
    time.perf_counter() 是专门用来测时间间隔的高精度时钟（比 time.time() 精确，不受系统改时间影响）。
    """

    def __init__(self):
        self.start = time.perf_counter()

    def ms(self) -> str:
        return f"[{(time.perf_counter() - self.start) * 1000:6.0f} ms]"


def cfg(thread_id: str) -> dict:
    """每一节用不同的 thread_id，互不影响（同一个 thread_id 会带上之前的对话记忆）"""
    return {"configurable": {"thread_id": f"lesson5-{thread_id}"}}


@tool
def diagnose_device(order_id: str) -> str:
    """对用户订单里的扫地机器人做一次远程诊断（检查传感器、电池、固件）。用户要求「远程诊断」「检测一下机器」时调用。"""
    # ↑ docstring 是发给模型看的工具说明，讲解写在这里的 # 注释里
    # 这是第 5 节演示用的工具：模拟一个要跑好几秒的诊断，每完成一步就往外推一条进度
    # get_stream_writer()：拿到当前这次运行的「自定义事件写入器」
    #   writer(任意可以转成 JSON 的数据) → 这条数据会出现在 stream_mode="custom" 里
    #   只能在 agent 运行过程中调用（工具、节点、中间件里），单独调用这个函数会报错
    writer = get_stream_writer()
    for step in ("连接设备", "检查激光雷达和碰撞传感器", "检查电池健康度", "检查固件版本"):
        writer({"order_id": order_id, "step": step})
        time.sleep(0.6)  # 模拟真实诊断的耗时
    return f"订单 {order_id} 的设备诊断完成：传感器正常，电池健康度 92%，固件已是最新版本。"


def lesson_agent(tools=None):
    """
    本课专用的小 agent：真实模型 + 订单工具，不带项目里的自定义中间件。
    第 5 节要用到演示工具 diagnose_device；第 6 节要演示异步，写这节时 build_agent() 里有 2 个自定义中间件
    只有同步版本，异步调用会报错，所以这两节用它。
    【v2 网页版】阶段 1 已给中间件补上异步版本（见 agent/middleware.py），第 6 节最后会用 build_agent() 再跑一次。
    """
    return create_agent(
        model=get_chat_model(),
        tools=tools or [list_my_orders, check_warranty],
        system_prompt="你是扫地机器人售后客服，回答简洁，不超过 80 字。用户的身份由系统提供，不要向用户索要。",
        context_schema=UserContext,  # list_my_orders 要从 runtime.context 读 user_id
        checkpointer=InMemorySaver(),
    )


def part1_invoke_vs_stream():
    title("1. invoke 和 stream：同一个问题，一个等全部结束才给，一个边跑边给")
    agent = build_agent()

    # ① invoke：调用期间程序卡在这一行，直到 agent 跑完整轮（模型 → 工具 → 模型）才返回
    clock = Clock()
    result = agent.invoke({"messages": [HumanMessage(QUESTION)]}, config=cfg("p1-invoke"), context=ZHANG)
    print(f"{clock.ms()} invoke 返回，回答 {len(result['messages'][-1].text)} 字。在这之前，用户什么都看不到")

    # ② stream：返回一个生成器，for 循环每拿到一条数据就能马上处理（打印、发给浏览器）
    #    stream_mode="messages"：每条数据是 (消息片段, 元数据) 二元组，见第 3 节
    clock = Clock()
    first_token_at = None
    for chunk, meta in agent.stream(
        {"messages": [HumanMessage(QUESTION)]}, config=cfg("p1-stream"), context=ZHANG, stream_mode="messages"
    ):
        # 只要模型节点（model）吐出的文字；工具节点（tools）的结果也会出现在这里，见第 3 节
        if meta["langgraph_node"] == "model" and chunk.text:
            if first_token_at is None:
                first_token_at = clock.ms()
                print(f"{first_token_at} 第一个片段到了：{chunk.text!r}")
    print(f"{clock.ms()} stream 结束")

    note("两次花的总时间差不多：流式不会让模型算得更快，也不省 token。")
    note("流式快的是「用户看到第一个字的时间」（首字时间）。2026-10-28 实测：invoke 2.1 秒后一次性拿到全部，"
         "stream 1.8 秒就出第一个字。这个问题回答短所以差距小；回答越长（几百字要生成十几秒），差距越大。")
    note("首字之前那段时间：第一次调用模型（决定调 list_my_orders）+ 执行工具 + 第二次调用模型开始出字。")


def part2_values_vs_updates():
    title("2. values 和 updates：按「步骤」给数据，一个给全量，一个给变化")
    agent = build_agent()
    for mode in ("values", "updates"):
        print(f"\n--- stream_mode='{mode}' ---")
        clock = Clock()
        for data in agent.stream(
            {"messages": [HumanMessage(QUESTION)]}, config=cfg(f"p2-{mode}"), context=ZHANG, stream_mode=mode
        ):
            if mode == "values":
                # values：每走完一步，给一份「当前完整的 State」（字典）。消息越多，每次给的数据越大
                last = data["messages"][-1]
                print(f"{clock.ms()} 完整 State：{len(data['messages'])} 条消息，最后一条 {type(last).__name__}，"
                      f"State 的键 {list(data.keys())}")
            else:
                # updates：每走完一步，给 {节点名: 这个节点返回的更新}。只有变化的部分，数据小
                for node, update in data.items():
                    keys = list(update.keys()) if isinstance(update, dict) else update
                    print(f"{clock.ms()} 节点「{node}」执行完，更新了 {keys}")

    note("两种模式都是「一步一条」：模型节点或工具节点执行完才给，节点执行期间（比如模型正在生成）没有数据。")
    note("values 适合调试、看 State 全貌；updates 适合显示进度（「正在查询订单…」）。")
    note("打字机效果做不了：要一个字一个字地显示，只能用第 3 节的 messages 模式。")
    note("updates 里除了 model、tools，每个中间件钩子也各算一个节点（如 track_token_usage.after_model）："
         "中间件本质上就是 create_agent 插进图里的节点。token_usage、run_model_call_count 这些键就是它们写进 State 的。")


def part3_messages_mode():
    title("3. messages：模型一边生成一边吐片段，还附带「这是谁、在哪一步」的元数据")
    agent = build_agent()
    clock = Clock()
    full_answer = None  # 用 + 把片段拼回完整消息
    for i, (chunk, meta) in enumerate(agent.stream(
        {"messages": [HumanMessage(QUESTION)]}, config=cfg("p3"), context=ZHANG, stream_mode="messages"
    )):
        node = meta["langgraph_node"]  # 哪个节点产生的：model（模型）或 tools（工具）
        # 图执行到第几步。每个节点都占一步，包括中间件钩子节点（见第 2 节），
        # 所以实测是「第 3 步模型、第 8 步工具、第 11 步模型」，不是 1、2、3
        step = meta["langgraph_step"]
        if isinstance(chunk, ToolMessage):
            # 工具节点执行完，它产生的 ToolMessage 也会整条出现在 messages 模式里（不是片段）
            print(f"{clock.ms()} 第{step}步 {node:<5} ToolMessage（整条）：{chunk.content[:50]}…")
        elif chunk.tool_call_chunks:
            # 模型决定调工具时，工具名和参数也是一段段生成的：tool_call_chunks 里是半截 JSON
            print(f"{clock.ms()} 第{step}步 {node:<5} 工具调用片段：{chunk.tool_call_chunks}")
        elif chunk.text:
            if i < 25:
                print(f"{clock.ms()} 第{step}步 {node:<5} 文字片段：{chunk.text!r}")
            # AIMessageChunk 支持 +：内容拼接、tool_call_chunks 合并、usage 累加，最后得到完整消息
            full_answer = chunk if full_answer is None else full_answer + chunk
    print(f"\n拼回来的完整回答：{full_answer.text}")
    print("元数据里还有：", sorted(k for k in meta.keys() if not k.startswith("__")))

    note("chunk 的类型是 AIMessageChunk（片段），不是 AIMessage。片段可以用 + 拼起来，命令行版就是边拼边打印。")
    note("一定要按 langgraph_node == 'model' 过滤：否则会把 ToolMessage（订单 JSON）当成回答显示给用户。")
    note("工具调用的参数也是一段段生成的半截 JSON，不能拿半截参数去执行工具：要等模型这一步生成完。")


def part4_multi_modes():
    title("4. 同时订阅多种模式：命令行版 agent.py 的 _run() 就是这么写的")
    agent = build_agent()
    clock = Clock()
    text_pieces = 0
    # stream_mode 传列表：每条数据变成 (模式名, 数据) 二元组，先看模式名再按模式解析
    for mode, data in agent.stream(
        {"messages": [HumanMessage(QUESTION)]}, config=cfg("p4"), context=ZHANG,
        stream_mode=["messages", "updates"],
    ):
        if mode == "messages":
            chunk, meta = data
            if meta["langgraph_node"] == "model" and chunk.text:
                text_pieces += 1  # 文字片段太多，只计数不逐条打印
        else:
            for node in data:
                print(f"{clock.ms()} updates：节点「{node}」完成（此时已收到 {text_pieces} 个文字片段）")
    note("messages 负责「字」（打字机），updates 负责「步骤」（工具调用了什么、结果是什么、有没有审批中断）。")
    note("回头看 agent/agent.py 的 _run()：mode == 'messages' → 产生 token 事件；mode == 'updates' → 产生 "
         "tool_call / tool_result / approval 事件。main.py 的 render() 再把这些事件打印出来。")


def part5_custom_mode():
    title("5. custom：工具自己往外推进度（get_stream_writer）")
    agent = lesson_agent(tools=[list_my_orders, diagnose_device])
    clock = Clock()
    for mode, data in agent.stream(
        {"messages": [HumanMessage("帮我给订单 SO20260312 的机器做个远程诊断")]},
        config=cfg("p5"), context=ZHANG, stream_mode=["custom", "updates"],
    ):
        if mode == "custom":
            # 这里拿到的就是 diagnose_device 里 writer(...) 写进去的字典，原样到达
            print(f"{clock.ms()} custom：{data}")
        else:
            print(f"{clock.ms()} updates：节点「{next(iter(data))}」完成")
    note("工具执行期间 updates 没有任何数据（它要等工具节点整个结束），custom 却能一步一条地报告进度。")
    note("真实项目用它做「正在检索知识库…」「已找到 10 条，正在重排…」这类提示。阶段 6 会给 search_knowledge 加上。")
    note("custom 的数据格式完全由你决定，框架不管；前端要按约定的字段去解析。")


def part6_astream():
    title("6. astream：异步版本。一个进程同时服务多个用户，网页后端靠的就是它")

    async def ask(agent, user: UserContext, clock: Clock):
        """一个用户问一个问题：async for 逐个取片段（等网络的时候把 CPU 让给别的用户）"""
        count = 0
        async for chunk, meta in agent.astream(
            {"messages": [HumanMessage(QUESTION)]}, config=cfg(f"p6-{user.user_id}"), context=user,
            stream_mode="messages",
        ):
            if meta["langgraph_node"] == "model" and chunk.text:
                count += 1
                if count <= 3:  # 每人只打印前 3 个片段，看两个人的片段是不是交替出现
                    print(f"{clock.ms()} {user.user_name}：{chunk.text!r}")
        print(f"{clock.ms()} {user.user_name} 结束，共 {count} 个片段")

    async def two_users():
        agent = lesson_agent()
        clock = Clock()
        # asyncio.gather：同时启动两个协程，谁的数据先到就先处理谁
        await asyncio.gather(ask(agent, ZHANG, clock), ask(agent, LI, clock))

    async def try_build_agent():
        """
        用项目的 build_agent() 走异步。
        【v2 网页版】阶段 1 之前这里会报 NotImplementedError；阶段 1 给中间件补了异步版本后，能正常跑完。
        """
        agent = build_agent()
        try:
            nodes = []
            async for chunk in agent.astream(
                {"messages": [HumanMessage(QUESTION)]}, config=cfg("p6-err"), context=ZHANG, stream_mode="updates"
            ):
                nodes.extend(chunk.keys())  # updates 模式：每块是 {节点名: 这个节点的更新}
            print(f"\n用 build_agent() 走 astream：正常跑完，经过的节点 {nodes}")
        except NotImplementedError as e:
            print(f"\n用 build_agent() 走 astream：报错 NotImplementedError\n  {str(e)[:150]}…")

    async def main():
        await two_users()
        await try_build_agent()

    # asyncio.run(协程)：创建事件循环、运行协程直到结束。普通脚本里运行 async 代码的入口
    # （FastAPI 里不用自己写这一句，uvicorn 已经开好了事件循环）
    # 【v2 网页版】两段演示放进同一个 asyncio.run：build_agent() 用的模型是缓存的单例，
    #   跨两个事件循环复用会报 RuntimeError: Event loop is closed（原因见 lessons/06 第 6 节的注释）
    asyncio.run(main())

    note("stream 是普通生成器，用 for；astream 是异步生成器，用 async for，只能写在 async def 里。拿到的数据完全一样。")
    note("两个人的片段交替出现，总时间约等于较慢那个人的时间，而不是两个人相加：等 DeepSeek 回包时不占着 CPU。")
    note("网页后端就是这种情况：同一个 FastAPI 进程要同时给很多浏览器推流，用同步写法会一个一个排队。")
    note("【v2 网页版】阶段 1 之前 build_agent() 走异步会报错：filter_tools_by_role、guard_tool_call 用 "
         "@wrap_model_call / @wrap_tool_call 装饰同步函数，只生成了同步版本。（build_system_prompt 用的 @dynamic_prompt "
         "会自动生成异步版本，没问题。）阶段 1 把这两个改成 AgentMiddleware 子类、同步异步各写一个方法，现在能正常跑完。")


if __name__ == "__main__":
    run_parts(
        {
            1: part1_invoke_vs_stream,
            2: part2_values_vs_updates,
            3: part3_messages_mode,
            4: part4_multi_modes,
            5: part5_custom_mode,
            6: part6_astream,
        },
        "stream / astream 练习",
    )
