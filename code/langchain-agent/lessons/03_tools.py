"""
【模块三：Tools】工具是怎么被模型「看见」、被程序执行、被拦住的

要回答的问题：
    @tool 把函数变成了什么？模型能看到哪些信息？runtime 参数为什么模型看不见？
    Pydantic 参数校验拦住了什么？拦住之后模型会知道吗？
    为什么用户身份放 context 而不让模型填？Command 怎么改 State？return_direct 有什么效果？
    工具报错时 agent 会不会崩？不同角色为什么看到的工具不一样？

全部离线运行：用「剧本模型」（tests/fakes.py）代替真实模型，固定模型的输出，专门观察程序这一侧的行为。
运行：python lessons/03_tools.py [--part N]
"""
import _common  # noqa: F401
from _common import note, run_parts, title

import json
import os
import tempfile

from pydantic import ValidationError

from agent.agent import CustomerServiceSession, build_agent
from agent.schemas import CreateTicketInput
from agent.state import UserContext
from agent.tools import ALL_TOOLS, check_warranty, get_order_detail, search_knowledge
from services.ticket_service import list_tickets
from tests.fakes import answer, call, scripted
from utils.config_handler import agent_conf

# 本脚本会创建工单：写到临时文件，不污染 data/runtime/tickets.json
agent_conf["data"]["tickets"] = os.path.join(tempfile.mkdtemp(), "tickets.json")

ZHANG = UserContext(user_id="U1001", user_name="张三", role="customer")
BOSS = UserContext(user_id="S9001", user_name="王主管", role="supervisor")


def run(context: UserContext, *replies):
    """用剧本模型跑一轮对话，返回 (session, 模型对象, 事件列表)"""
    model = scripted(*replies)
    session = CustomerServiceSession(build_agent(model=model, use_backup_models=False), context)
    events = list(session.ask("（用户的话不重要，模型的行为由剧本决定）"))
    return session, model, events


def tool_results(events):
    return [e for e in events if e[0] == "tool_result"]


def part1_what_model_sees():
    title("1. @tool 之后，模型能看到什么")
    for t in (get_order_detail, check_warranty):
        print(f"\n工具名：{t.name}")
        print(f"描述（来自 docstring）：{t.description}")
        # tool_call_schema：真正发给模型的参数结构（去掉了 runtime 这类框架注入的参数）
        print("发给模型的参数 schema：")
        print(json.dumps(t.tool_call_schema.model_json_schema(), ensure_ascii=False, indent=2))
    note("函数签名里有 runtime: ToolRuntime，但上面的 schema 里没有它 —— 模型看不见，也就没法伪造。")
    note("Literal 变成了 enum、pattern 变成了正则约束、Field 的 description 都在里面：这些就是模型填参数的依据。")
    print("\nsearch_knowledge 的 response_format：", search_knowledge.response_format)


def part2_pydantic():
    title("2. Pydantic 参数校验：模型填错参数时会怎样")
    bad_inputs = [
        {"order_id": "我买的那台", "fault_category": "拖地漏水", "description": "一直漏水"},
        {"order_id": "SO20260312", "fault_category": "坏了", "description": "机器坏了不能用了"},
        {"order_id": "SO20260312", "fault_category": "拖地漏水", "description": "漏"},
    ]
    for data in bad_inputs:
        try:
            CreateTicketInput(**data)
        except ValidationError as e:
            print(f"{data}\n   → 拦下：{[(err['loc'][0], err['msg']) for err in e.errors()]}")

    print("\n放到 agent 里：模型第一次填错订单号，第二次改对")
    session, model, events = run(
        ZHANG,
        call("get_order_detail", {"order_id": "我买的X1 Pro"}, "c1"),
        call("get_order_detail", {"order_id": "SO20260312"}, "c2"),
        answer("查到了"),
    )
    for e in tool_results(events):
        print(f"   [工具结果] {str(e[2])[:120]}")
    note("校验失败不会让程序崩溃：错误信息作为 ToolMessage 回给模型（Please fix the error and try again），模型可以自己改正。")


def part3_context_isolation():
    title("3. 用户身份放在 context：模型被诱导也查不到别人的订单")
    # 剧本：模型被用户说服，去查 U1002（李四）的订单
    session, model, events = run(
        ZHANG,
        call("get_order_detail", {"order_id": "SO20250601"}, "c1"),
        answer("抱歉，无法查询"),
    )
    for e in tool_results(events):
        print(f"   张三查李四的订单 → {e[2]}")

    session, model, events = run(
        BOSS,
        call("get_order_detail", {"order_id": "SO20250601"}, "c1"),
        answer("查到了"),
    )
    for e in tool_results(events):
        print(f"   客服主管查同一个订单 → {str(e[2])[:80]}…")
    note("工具里的 user_id 来自 runtime.context（程序登录时决定），不是模型参数。")
    note("拦截发生在 services/order_service.py：不管模型怎么填，规则都在代码里。")


def part4_command_state():
    title("4. Command：工具执行完顺便更新 State")
    session, model, events = run(
        ZHANG,
        call("get_order_detail", {"order_id": "SO20260312"}, "c1"),
        answer("这台机器是 X1 Pro"),
    )
    state = session.state()
    print("State 里的 current_order_id：", state.get("current_order_id"))
    print("最后一次发给模型的系统提示词里：")
    system_prompt = model.received[-1][0].content
    print("  ", [line for line in system_prompt.splitlines() if "正在处理的订单" in line][0])
    note("get_order_detail 返回 Command(update={...})，把 current_order_id 写进 State；")
    note("下一次调用模型前，build_system_prompt 中间件把它填进提示词，用户说「这台」时模型就知道指哪台。")


def part5_return_direct():
    title("5. return_direct：工具结果直接作为最终回答")
    session, model, events = run(
        ZHANG,
        call("create_repair_ticket", {"order_id": "SO20260312", "fault_category": "拖地漏水", "description": "拖地时一直漏水"}, "c1"),
        answer("工单已提交"),
    )
    list(session.resume(approved=True))  # 建单需要审批，这里直接批准（审批细节见 lessons/04）
    ticket_id = list_tickets("U1001")[0]["ticket_id"]
    print("先建了一张工单：", ticket_id)

    session, model, events = run(ZHANG, call("get_ticket_status", {"ticket_id": ticket_id}, "c1"))
    finals = [e for e in events if e[0] == "final"]
    print("模型一共被调用了", len(model.received), "次")
    print("最终回答：", finals[0][1] if finals else None)
    note("剧本里只准备了 1 条模型回复，没有出错，说明工具执行完就直接结束了，没有再调用模型。")
    note("适合结果格式固定、不需要模型再加工的工具；需要模型分析结果的工具不要用。")


def part6_errors():
    title("6. 工具报错时：guard_tool_call 中间件把异常变成消息")
    os.environ.pop("CHROMA_HOST", None)
    from utils.config_handler import chroma_conf
    chroma_conf["host"] = ""  # 模拟没配好 Chroma 地址，知识库工具会抛 RuntimeError
    session, model, events = run(
        ZHANG,
        call("search_knowledge", {"query": "扫地机器人迷路怎么办"}, "c1"),
        answer("系统繁忙，请稍后再试"),
    )
    for e in tool_results(events):
        print("   模型收到的工具结果：", e[2])
    note("上面那段 Traceback 是写给开发者的日志（同时保存在 logs/）；")
    note("模型只收到一句不含内部细节的话，agent 继续运行，不会因为一个工具出错整轮崩溃。")


def part7_role_tools():
    title("7. 不同角色，模型看到的工具不同")
    for ctx in (ZHANG, BOSS):
        session, model, events = run(ctx, answer("您好"))
        print(f"{ctx.user_name}（{ctx.role}）这次调用模型时能看到的工具：")
        print("   ", model.tools_seen[-1])
    note("filter_tools_by_role 中间件在每次调用模型前改写工具列表。普通用户的请求里根本没有 update_ticket_status。")
    note("这只是第一道防线；services/ticket_service.update_status 里还会再检查一次角色。")
    print("\n全部工具：", [t.name for t in ALL_TOOLS])


if __name__ == "__main__":
    run_parts(
        {
            1: part1_what_model_sees,
            2: part2_pydantic,
            3: part3_context_isolation,
            4: part4_command_state,
            5: part5_return_direct,
            6: part6_errors,
            7: part7_role_tools,
        },
        "Tools 模块练习",
    )
