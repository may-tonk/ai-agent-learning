"""
【模块四：Agents】create_agent 组装起来之后，一轮对话里到底发生了什么

要回答的问题：
    invoke 返回了什么？stream 的三种模式分别给什么？
    checkpointer + thread_id 怎么实现多轮记忆？换个 thread_id 为什么就「忘了」？
    人工审批时 agent 停在哪里、怎么继续？
    response_format 怎么让 agent 最终返回结构化数据？
    调用次数上限、对话摘要这些中间件实际效果是什么？

需要：DEEPSEEK_API_KEY；第 1 节和问知识库的问题还需要 Chroma（CHROMA_HOST）和 DASHSCOPE_API_KEY
运行：python lessons/04_agents.py [--part N]
注意：模型每次的措辞、调用工具的顺序可能不同，这是正常的；重点看结构和流程。
"""
import _common  # noqa: F401
from _common import note, run_parts, title

import os
import tempfile

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, SummarizationMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent.agent import CustomerServiceSession, build_agent
from agent.middleware import build_system_prompt, filter_tools_by_role, track_token_usage
from agent.schemas import DeviceWarrantyReport
from agent.state import CustomerServiceState, UserContext
from agent.tools import ALL_TOOLS, check_warranty, list_my_orders
from model.factory import build_chat_model, get_chat_model
from utils.config_handler import agent_conf

# 本脚本会创建工单：写到临时文件，不污染 data/runtime/tickets.json
agent_conf["data"]["tickets"] = os.path.join(tempfile.mkdtemp(), "tickets.json")

ZHANG = UserContext(user_id="U1001", user_name="张三", role="customer")
LI = UserContext(user_id="U1002", user_name="李四", role="customer")


def show(messages):
    for i, m in enumerate(messages, start=1):
        line = f"  {i:>2}. {type(m).__name__:<12}"
        if isinstance(m, AIMessage) and m.tool_calls:
            line += f"请求工具 {[(c['name'], c['args']) for c in m.tool_calls]}"
        elif isinstance(m, ToolMessage):
            line += f"[{m.name}] {str(m.content)[:60]}"
        else:
            line += str(m.content)[:70].replace("\n", " ")
        print(line)


def part1_invoke():
    title("1. invoke：跑完一整轮，返回最终的 State")
    agent = build_agent()
    result = agent.invoke(
        {"messages": [HumanMessage("扫地机器人总是迷路怎么办？")]},
        config={"configurable": {"thread_id": "lesson4-part1"}},
        context=ZHANG,
    )
    print("返回值的键：", list(result.keys()))
    print("消息链：")
    show(result["messages"])
    print("token 累计：", result.get("token_usage"))
    note("invoke 返回的是这一轮结束时的完整 State（不只是回答），回答是 result['messages'][-1]。")
    note("中间的 AIMessage(请求工具) → ToolMessage 就是 lessons/02 里手写循环做的事，这次由 create_agent 完成。")


def part2_stream_modes():
    title("2. stream 的三种模式：values / updates / messages")
    agent = build_agent()
    question = {"messages": [HumanMessage("我有哪些订单？")]}

    for mode in ("values", "updates", "messages"):
        print(f"\n--- stream_mode='{mode}' ---")
        config = {"configurable": {"thread_id": f"lesson4-part2-{mode}"}}
        for i, data in enumerate(agent.stream(question, config=config, context=ZHANG, stream_mode=mode)):
            if mode == "values":
                print(f"  第{i + 1}次：完整 State，共 {len(data['messages'])} 条消息，最后一条是 {type(data['messages'][-1]).__name__}")
            elif mode == "updates":
                for node, update in data.items():
                    keys = list(update.keys()) if isinstance(update, dict) else update
                    print(f"  节点 {node} 执行完，更新了 {keys}")
            else:
                chunk, meta = data
                if i < 8:
                    print(f"  来自节点 {meta['langgraph_node']}：{type(chunk).__name__} {chunk.content!r}")
                elif i == 8:
                    print("  ……（后面还有很多片段，省略）")
    note("values：每一步之后的完整 State，数据最全也最重。")
    note("updates：每个节点「改了什么」，适合显示进度（正在查订单…）。")
    note("messages：模型一边生成一边吐出的片段，适合打字机效果。main.py 同时用了 updates 和 messages。")


def part3_memory():
    title("3. checkpointer + thread_id：多轮记忆")
    agent = build_agent()
    session = CustomerServiceSession(agent, ZHANG)

    def ask(text):
        print(f"\n用户：{text}")
        answer = "".join(e[1] for e in session.ask(text) if e[0] in ("token", "final"))
        print(f"客服：{answer[:150]}")

    ask("我的订单 SO20260312 那台机器拖地的时候漏水")
    ask("这台还在保修期吗？")  # 「这台」能被理解：靠 State 里的历史消息和 current_order_id
    state = session.state()
    print("\nState：current_order_id =", state.get("current_order_id"), "｜消息数 =", len(state["messages"]))
    history = list(agent.get_state_history(session.config))
    print("这个 thread 一共存了", len(history), "个检查点（每走一步存一个）")

    print("\n换一个 thread_id（相当于新开一个聊天窗口）：", session.new_thread())
    ask("这台还在保修期吗？")
    note("同一个 thread_id：checkpointer 自动把之前的消息加载回来；新 thread_id：State 是空的，模型不知道「这台」是哪台。")
    note("InMemorySaver 存在内存里，程序一退出就没了；正式项目换成 PostgresSaver，代码只改 checkpointer 这一个参数。")


def part4_context():
    title("4. context：同一个 agent、同一句话，不同用户结果不同")
    agent = build_agent()
    for ctx in (ZHANG, LI):
        session = CustomerServiceSession(agent, ctx)
        answer = "".join(e[1] for e in session.ask("我有哪些订单？") if e[0] in ("token", "final"))
        print(f"\n{ctx.user_name}：{answer[:200]}")
    note("agent 只建了一个。用户身份通过 invoke(context=...) 每次传入，工具从 runtime.context 读取。")


def part5_human_in_the_loop():
    title("5. 人工审批：agent 停在哪里，怎么继续")
    agent = build_agent()
    session = CustomerServiceSession(agent, ZHANG)
    text = "我的订单 SO20260312 那台 X1 Pro 拖地一直漏水，地板都湿了，帮我报修，加急。"
    print("用户：", text)
    events = list(session.ask(text))
    for e in events:
        if e[0] == "tool_call":
            print(f"  [调用工具] {e[1]} {e[2]}")

    snapshot = agent.get_state(session.config)
    print("\n暂停中，下一个要执行的节点：", snapshot.next)
    pending = session.pending_approvals()
    if not pending:
        print("模型这次没有直接提交工单（可能先在确认信息），重新运行一次即可")
        return
    print("等待审批的操作：", pending[0]["name"], pending[0]["args"])

    print("\n客服选择【拒绝】，理由：请先确认用户是否已检查水箱安装")
    reply = "".join(e[1] for e in session.resume(False, "请先确认用户是否已检查水箱安装是否到位") if e[0] in ("token", "final"))
    print("客服回复用户：", reply[:200])

    print("\n用户：检查过了，水箱装好了还是漏，请提交吧")
    events = list(session.ask("检查过了，水箱装好了还是漏，请提交吧"))
    if session.pending_approvals():
        print("客服选择【批准】")
        events = list(session.resume(True))
    for e in events:
        if e[0] == "tool_result":
            print(f"  [工具结果] {e[1]}：{e[2]}")
        if e[0] == "token":
            print(e[1], end="")
    print()
    note("HumanInTheLoopMiddleware 在模型「决定调用工具」之后、工具「真正执行」之前暂停（snapshot.next 指向 tools）。")
    note("暂停时 State 存在 checkpointer 里，所以审批可以在几分钟甚至几小时之后再继续。没有 checkpointer 就不能用审批。")
    note("拒绝时的理由会作为 ToolMessage 交给模型，模型据此回复用户。")


def part6_response_format():
    title("6. response_format：让 agent 最后返回结构化数据")
    agent = create_agent(
        model=get_chat_model(),
        tools=[list_my_orders, check_warranty],
        system_prompt="你负责生成「我的设备」页面的数据。先列出用户订单，再对每个已签收订单查询主机（故障类型选「其他」）的保修情况。",
        context_schema=UserContext,
        # ToolStrategy：把 DeviceWarrantyReport 当作一个特殊的「工具」，模型调用它就等于交出最终结果
        response_format=ToolStrategy(DeviceWarrantyReport),
    )
    result = agent.invoke({"messages": [HumanMessage("生成我的设备保修情况")]}, context=ZHANG)
    report = result["structured_response"]
    print("structured_response 的类型：", type(report).__name__)
    print(report.model_dump_json(indent=2))
    note("和 lessons/01 第 9 节的 with_structured_output 区别：那是「一次模型调用」直接要结构化结果；")
    note("这里是 agent 先调用工具收集数据（可能好几轮），最后一步才按结构交结果。前端拿到的就是固定字段的 JSON。")


def part7_call_limit():
    title("7. ModelCallLimitMiddleware：一轮最多调用几次模型")
    agent = create_agent(
        model=get_chat_model(),
        tools=ALL_TOOLS,
        middleware=[ModelCallLimitMiddleware(run_limit=1, exit_behavior="end"), build_system_prompt, filter_tools_by_role],
        state_schema=CustomerServiceState,
        context_schema=UserContext,
        checkpointer=InMemorySaver(),
    )
    result = agent.invoke(
        {"messages": [HumanMessage("我有哪些订单？")]},
        config={"configurable": {"thread_id": "lesson4-part7"}},
        context=ZHANG,
    )
    show(result["messages"])
    note("模型第 1 次调用请求了工具，但上限是 1 次，agent 没有再调用模型就结束了，最后一条是中间件写的提示。")
    note("正式配置里上限是 config/agent.yml 的 model_call_run_limit=8，防止模型陷入反复调用工具的死循环。")


def part8_summarization():
    title("8. SummarizationMiddleware：对话太长时自动压缩")
    agent = create_agent(
        model=get_chat_model(),
        tools=[],
        middleware=[
            # 为了演示把门槛调得很低：消息超过 6 条就压缩，只保留最近 2 条原文
            SummarizationMiddleware(model=build_chat_model("summary"), trigger=("messages", 6), keep=("messages", 2)),
            track_token_usage,
        ],
        system_prompt="你是扫地机器人售后客服，每次回答不超过 30 字。",
        state_schema=CustomerServiceState,
        context_schema=UserContext,
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "lesson4-part8"}}
    for text in ["我叫张三，机器是 X1 Pro", "最近总是迷路", "重新建图要多久", "建图时宠物要关起来吗", "我刚才说我的机器是什么型号？"]:
        result = agent.invoke({"messages": [HumanMessage(text)]}, config=config, context=ZHANG)
        print(f"用户：{text}\n   客服：{result['messages'][-1].text[:60]}｜State 里现在有 {len(result['messages'])} 条消息")
    print("\n压缩后的第一条消息（摘要）：")
    print("  ", str(result["messages"][0].content)[:300])
    note("超过门槛后，旧消息被替换成一条摘要，State 里的消息数降下来，每次发给模型的 token 也就降下来。")
    note("最后一问「型号是什么」：原始消息已经被压缩掉了，模型是从摘要里找到 X1 Pro 的。")


if __name__ == "__main__":
    run_parts(
        {
            1: part1_invoke,
            2: part2_stream_modes,
            3: part3_memory,
            4: part4_context,
            5: part5_human_in_the_loop,
            6: part6_response_format,
            7: part7_call_limit,
            8: part8_summarization,
        },
        "Agents 模块练习",
    )
