"""
agent 流程测试：用剧本模型（tests/fakes.py）固定模型输出，检查程序这一侧的行为
不需要 API key，不联网，几秒钟跑完。改了中间件、工具、State 之后先跑这个，确认没有改坏。
"""
from agent.agent import CustomerServiceSession, build_agent
from agent.state import UserContext
from services import ticket_service
from tests.fakes import answer, call, scripted

ZHANG = UserContext("U1001", "张三", "customer")
BOSS = UserContext("S9001", "王主管", "supervisor")


def session_with(ctx, *replies):
    model = scripted(*replies)
    return CustomerServiceSession(build_agent(model=model, use_backup_models=False), ctx), model


def results(events):
    return [e for e in events if e[0] == "tool_result"]


def test_other_users_order_is_refused():
    s, _ = session_with(ZHANG, call("get_order_detail", {"order_id": "SO20250601"}), answer("抱歉"))
    events = list(s.ask("查李四的订单"))
    assert "不属于当前用户" in results(events)[0][2]


def test_invalid_args_are_returned_to_model():
    s, model = session_with(ZHANG, call("get_order_detail", {"order_id": "我的订单"}), answer("请提供订单号"))
    events = list(s.ask("查我的订单"))
    assert "should match pattern" in results(events)[0][2]
    assert len(model.received) == 2  # 校验失败后模型又被调用了一次，有机会改正


def test_command_updates_current_order_and_prompt():
    s, model = session_with(ZHANG, call("get_order_detail", {"order_id": "SO20260312"}), answer("好的"))
    list(s.ask("查 SO20260312"))
    assert s.state()["current_order_id"] == "SO20260312"
    assert "正在处理的订单：SO20260312" in model.received[-1][0].content


def test_ticket_needs_approval_and_reject_creates_nothing():
    args = {"order_id": "SO20260312", "fault_category": "拖地漏水", "description": "拖地时一直漏水"}
    s, _ = session_with(ZHANG, call("create_repair_ticket", args), answer("已转人工确认"))
    events = list(s.ask("报修"))
    assert any(e[0] == "approval" for e in events)
    assert ticket_service.list_tickets("U1001") == []  # 暂停时还没执行
    list(s.resume(approved=False, reason="信息不全"))
    assert ticket_service.list_tickets("U1001") == []


def test_ticket_created_after_approval():
    args = {"order_id": "SO20260312", "fault_category": "拖地漏水", "description": "拖地时一直漏水"}
    s, _ = session_with(ZHANG, call("create_repair_ticket", args), answer("工单已提交"))
    list(s.ask("报修"))
    events = list(s.resume(approved=True))
    assert "保修内免费" in results(events)[0][2]
    assert len(ticket_service.list_tickets("U1001")) == 1


def test_role_filter_hides_supervisor_tool():
    s, model = session_with(ZHANG, answer("您好"))
    list(s.ask("你好"))
    assert "update_ticket_status" not in model.tools_seen[-1]

    s2, boss_model = session_with(BOSS, answer("您好"))
    list(s2.ask("你好"))
    assert "update_ticket_status" in boss_model.tools_seen[-1]


def test_token_usage_accumulates_across_turns():
    s, _ = session_with(ZHANG, answer("第一轮"), answer("第二轮"))
    list(s.ask("1"))
    list(s.ask("2"))
    usage = s.state()["token_usage"]
    assert usage["model_calls"] == 2 and usage["total_tokens"] == 380


def test_new_thread_forgets_history():
    s, _ = session_with(ZHANG, answer("第一轮"), answer("新对话"))
    list(s.ask("1"))
    s.new_thread()
    list(s.ask("2"))
    assert len(s.state()["messages"]) == 2
