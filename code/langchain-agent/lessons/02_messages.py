"""
【模块二：Messages】不用 create_agent，自己把「模型 ⇄ 工具」循环写一遍

要回答的问题：
    四种消息分别是谁产生的？AIMessage 里的 tool_calls 是不是已经执行了工具？
    tool_call_id 对不上会怎样？artifact 里的数据模型能看到吗？
    create_agent 每一轮到底在帮我们做什么？

需要：第 2、3 节调用 DeepSeek；第 1、4、5、6 节不需要 key，离线就能跑
运行：python lessons/02_messages.py [--part N]
"""
import _common  # noqa: F401
from _common import note, run_parts, title

import json

from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.tools import tool
from langchain_core.exceptions import ModelError
from langchain_core.load import dumpd, load
from langchain_core.messages import AIMessageChunk, convert_to_openai_messages
from langgraph.graph.message import add_messages

from model.factory import get_chat_model
from services import order_service, warranty_service

# 本节固定以 U1001 的身份查询。正式代码里用户身份来自 ToolRuntime.context（见 lessons/03）
DEMO_USER = "U1001"


# ---- 本节用的两个简化工具：直接调用项目里的 service ----
@tool
def lookup_order(order_id: str) -> str:
    """查询订单详情（产品、购买日期、状态）。order_id 格式为 SO 加 8 位数字。"""
    order = order_service.get_order(order_id, DEMO_USER)
    return json.dumps({k: order[k] for k in ("order_id", "product", "purchase_date", "status")}, ensure_ascii=False)


@tool
def warranty(order_id: str, fault_category: str) -> str:
    """判断订单的机器在某种故障下是否在保修期内。fault_category 可选：无法开机或充电、续航明显变短、导航迷路或建图异常、吸力下降、噪音异常、拖地漏水、滚刷边刷损坏、其他。"""
    order = order_service.get_order(order_id, DEMO_USER)
    return json.dumps(warranty_service.check_warranty(order, fault_category), ensure_ascii=False)


TOOLS = {t.name: t for t in (lookup_order, warranty)}  # 名字 → 工具对象（白名单）


def show(messages):
    """把消息列表按「类型 + 关键字段」打印出来"""
    for i, m in enumerate(messages, start=1):
        line = f"  {i}. {type(m).__name__:<14}"
        if isinstance(m, AIMessage) and m.tool_calls:
            line += f"tool_calls = {[(c['name'], c['args'], c['id']) for c in m.tool_calls]}"
        elif isinstance(m, ToolMessage):
            line += f"tool_call_id = {m.tool_call_id}｜{str(m.content)[:60]}"
        else:
            line += str(m.content)[:70].replace("\n", " ")
        print(line)


def part1_four_types():
    title("1. 四种消息：谁产生、长什么样")
    msgs = [
        SystemMessage("你是售后客服"),                       # 开发者写的规则
        HumanMessage("我的订单到哪了"),                      # 用户说的话
        AIMessage(                                          # 模型的输出：这一条是「请求调用工具」
            content="",
            tool_calls=[{"name": "lookup_order", "args": {"order_id": "SO20261018"}, "id": "call_001", "type": "tool_call"}],
        ),
        ToolMessage(content='{"status": "运输中"}', tool_call_id="call_001", name="lookup_order"),  # 程序执行工具后的结果
        AIMessage("您的订单正在运输中。"),                    # 模型的输出：这一条是最终回答
    ]
    show(msgs)
    print("\n每条消息的 type 属性：", [m.type for m in msgs])
    print("\n发给 DeepSeek（OpenAI 格式）时会变成：")
    for m in convert_to_openai_messages(msgs):
        print("  ", m)
    note("两条 AIMessage：第一条只有 tool_calls 没有文字（请求工具），第二条有文字（最终回答）。")
    note("ToolMessage 在发给模型时 role 是 tool，并带着 tool_call_id —— 模型靠它知道这是哪次调用的结果。")


def part2_manual_loop():
    title("2. 手写工具循环：这就是 create_agent 每一轮在做的事")
    model = get_chat_model().bind_tools(list(TOOLS.values()))  # 把工具的说明书交给模型（不会执行任何工具）

    messages = [
        SystemMessage("你是扫地机器人售后客服。需要查询时调用工具，根据工具结果回答，不要编造。"),
        HumanMessage("我的订单 SO20251015 那台机器最近吸力变小了，还在保修期吗？"),
    ]

    for step in range(1, 6):  # 最多 5 轮，防止死循环（create_agent 里对应 ModelCallLimitMiddleware）
        ai: AIMessage = model.invoke(messages)
        messages.append(ai)
        print(f"\n第 {step} 次调用模型 → {'请求工具 ' + str([c['name'] for c in ai.tool_calls]) if ai.tool_calls else '给出最终回答'}")

        if not ai.tool_calls:  # 没有工具请求 = 模型认为可以回答了，循环结束
            break

        for call in ai.tool_calls:
            # 到这里工具还没有执行！tool_calls 只是模型写的一张「请求单」
            selected = TOOLS.get(call["name"])
            if selected is None:
                result = f"不存在工具 {call['name']}"
            else:
                result = selected.invoke(call["args"])  # 这一行才真正执行 Python 函数
            # 把结果包成 ToolMessage，tool_call_id 必须等于这次请求的 id
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"], name=call["name"]))
            print(f"   执行 {call['name']}({call['args']}) → {str(result)[:80]}")

    print("\n完整消息链：")
    show(messages)
    print("\n最终回答：", messages[-1].text)
    note("create_agent 把上面的 for 循环、工具查找、ToolMessage 打包、轮数限制全部做好了，所以我们平时不用自己写。")


def part3_bad_tool_call_id():
    title("3. tool_call_id 对不上会怎样")
    model = get_chat_model().bind_tools([lookup_order])
    messages = [HumanMessage("查一下订单 SO20261018 的状态")]
    ai = model.invoke(messages)
    if not ai.tool_calls:
        print("模型这次没有请求工具，重新运行一次即可")
        return
    real_id = ai.tool_calls[0]["id"]
    messages += [ai, ToolMessage(content='{"status": "运输中"}', tool_call_id="call_wrong_id")]
    print("模型请求的 id：", real_id, "｜我们回填的 id：call_wrong_id")
    try:
        model.invoke(messages)
        print("这次居然没报错")
    except ModelError as e:
        print("报错类型：", type(e).__name__)
        print("报错内容：", str(e)[:200])
    note("模型提供方要求：每个 tool_call 后面必须跟一条 id 相同的 ToolMessage，否则整次请求被拒绝。")
    note("这就是为什么 order_tools.py 里用 Command 写 ToolMessage 时，必须写 tool_call_id=runtime.tool_call_id。")


def part4_artifact():
    title("4. artifact：给程序用、但不发给模型的数据")

    @tool(response_format="content_and_artifact")
    def fake_search(query: str) -> tuple[str, list[dict]]:
        """模拟知识库检索"""
        hits = [{"content": "建图前清理地面障碍物", "source": "维护保养.txt", "distance": 0.42}]
        return "【资料1】建图前清理地面障碍物", hits

    # 用「完整的工具调用」去 invoke，工具会直接返回 ToolMessage（和 agent 里一样）
    msg = fake_search.invoke({"name": "fake_search", "args": {"query": "建图"}, "id": "call_9", "type": "tool_call"})
    print("返回类型：", type(msg).__name__)
    print("content  ：", msg.content)
    print("artifact ：", msg.artifact)
    print("发给模型时：", convert_to_openai_messages([msg]))
    note("发给模型的只有 content。来源文件、分数这些放在 artifact，main.py 用它显示「参考资料」，不花 token。")


def part5_text_and_stream():
    title("5. content / text / content_blocks，以及流式片段怎么合并")
    msg = AIMessage(content=[{"type": "text", "text": "已为您查询。"}, {"type": "text", "text": "订单正在运输中。"}])
    print("content        ：", msg.content, " ← 原始格式，可能是字符串也可能是列表")
    print("text           ：", msg.text, " ← 只取文字，最常用")
    print("content_blocks ：", msg.content_blocks, " ← LangChain 统一后的标准格式")

    print("\n流式时模型返回的是一块块 AIMessageChunk：")
    chunks = [
        AIMessageChunk(content="您的", tool_call_chunks=[]),
        AIMessageChunk(content="订单", tool_call_chunks=[]),
        AIMessageChunk(content="", tool_call_chunks=[{"name": "lookup_order", "args": '{"order_', "id": "call_1", "index": 0}]),
        AIMessageChunk(content="", tool_call_chunks=[{"name": None, "args": 'id": "SO20261018"}', "id": None, "index": 0}]),
    ]
    merged = chunks[0]
    for c in chunks[1:]:
        merged = merged + c
    print("合并后 text      ：", merged.text)
    print("合并后 tool_calls：", merged.tool_calls)
    note("工具参数也是一段段到达的（'{\"order_' + 'id\": ...'），必须全部合并后才能解析成完整参数再执行工具。")


def part6_add_messages_and_serialize():
    title("6. add_messages：State 里的消息是怎么「追加」的；消息怎么存盘")
    old = [HumanMessage("你好", id="m1"), AIMessage("您好，请问有什么可以帮您", id="m2")]
    new = [HumanMessage("查订单", id="m3")]
    print("追加：", [(m.id, m.content) for m in add_messages(old, new)])

    fix = [AIMessage("您好，我是智扫通客服，请问有什么可以帮您", id="m2")]
    print("同 id 替换：", [(m.id, m.content) for m in add_messages(old, fix)])
    note("节点返回 {'messages': [新消息]} 时，不会覆盖原列表，而是经过 add_messages 追加；id 相同则替换。")
    note("这就是 agent 里每个节点只返回「新消息」就够了的原因。")

    data = dumpd(old[0])
    print("\n序列化成字典：", data)
    print("再还原：", repr(load(data, allowed_objects="core")))
    note("checkpointer 存 State 时也要做类似的序列化。load 只能用于自己存的可信数据。")


if __name__ == "__main__":
    run_parts(
        {
            1: part1_four_types,
            2: part2_manual_loop,
            3: part3_bad_tool_call_id,
            4: part4_artifact,
            5: part5_text_and_stream,
            6: part6_add_messages_and_serialize,
        },
        "Messages 模块练习",
    )
