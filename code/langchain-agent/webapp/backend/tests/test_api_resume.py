"""
【v2 网页版新增 · 阶段 3】审批后继续（POST /api/chat/resume）和「停止」之后的存档修补

和 test_api_stream.py 一样用假模型把模型输出固定下来，检查的是程序逻辑：
    批准：resume 之后工具真的执行（tool_started → tool_finished），模型接着回答，done(completed)
    拒绝：工具不执行，拒绝理由作为工具结果交给模型
    检查：没有待审批时 409、别人的会话 403、缺字段 422 —— 都在开始推流之前返回
    停止：上一轮停在工具执行中（存档里有「请求工具」的 AIMessage 但没有 ToolMessage），
          下一句发出前要补上 ToolMessage，否则真实 DeepSeek 会报 400（runtime/stop_probe.py 实测）
「浏览器断开时后端真的取消了运行」要连真实后端看日志，测试里模拟不了，见讲解文档的实测部分。
"""
from fastapi.testclient import TestClient
from langchain.messages import AIMessage, HumanMessage, ToolMessage

from tests.fakes import answer, call, scripted
from webapp.backend.app import create_app
from webapp.backend.tests.test_api_stream import LI, MEMORY, ZHANG, names, parse_sse, stream

TICKET_ARGS = {"order_id": "SO20260312", "fault_category": "拖地漏水", "description": "拖地时一直漏水"}


def resume(client, thread_id, approved, reason="", headers=ZHANG):
    """发一次审批请求，返回 (响应, 事件列表)"""
    r = client.post(
        "/api/chat/resume",
        json={"thread_id": thread_id, "approved": approved, "reason": reason},
        headers=headers,
    )
    return r, (parse_sse(r.text) if r.status_code == 200 else [])


def test_approve_runs_tool_then_model_answers():
    model = scripted(call("create_repair_ticket", TICKET_ARGS, call_id="t1"), answer("已为您创建报修单"), answer("不客气"))
    with TestClient(create_app(model=model, checkpointer_conf=MEMORY)) as c:
        _, first = stream(c, "帮我报修")
        tid = first[0][1]["thread_id"]
        assert first[-1][1]["status"] == "interrupted"
        r, events = resume(c, tid, approved=True)
        # 审批完成后，这段对话可以正常接着聊（不再 409）
        r2, _ = stream(c, "谢谢", thread_id=tid)
    assert r.headers["content-type"].startswith("text/event-stream")
    assert names(events) == ["run_started", "tool_started", "tool_finished", "token", "done"]
    assert events[1][1]["name"] == "create_repair_ticket" and events[2][1]["ok"] is True
    done = events[-1][1]
    assert done["status"] == "completed" and done["answer"] == "已为您创建报修单"
    assert done["pending_approvals"] == []
    assert r2.status_code == 200


def test_reject_skips_tool_and_tells_model_why():
    model = scripted(call("create_repair_ticket", TICKET_ARGS, call_id="t1"), answer("好的，报修单没有提交"))
    with TestClient(create_app(model=model, checkpointer_conf=MEMORY)) as c:
        _, first = stream(c, "帮我报修")
        _, events = resume(c, first[0][1]["thread_id"], approved=False, reason="故障描述不清楚")
    # 拒绝：工具根本没执行，所以没有 tool_started / tool_finished
    assert names(events) == ["run_started", "token", "done"]
    assert events[-1][1]["status"] == "completed"
    # 模型第二次被调用时，看到的最后一条是「拒绝理由」变成的工具结果
    last = model.received[-1][-1]
    assert isinstance(last, ToolMessage) and "故障描述不清楚" in str(last.content)


def test_resume_checks_happen_before_streaming():
    model = scripted(answer("您好"))
    with TestClient(create_app(model=model, checkpointer_conf=MEMORY)) as c:
        _, first = stream(c, "你好")
        tid = first[0][1]["thread_id"]
        r_none, _ = resume(c, tid, approved=True)  # 没停在审批上
        r_other, _ = resume(c, tid, approved=True, headers=LI)  # 李四动张三的会话
        r_bad = c.post("/api/chat/resume", json={"thread_id": tid}, headers=ZHANG)  # 缺 approved
    assert r_none.status_code == 409
    assert r_other.status_code == 403
    assert r_bad.status_code == 422


def test_stopped_run_is_repaired_before_next_message():
    model = scripted(answer("好的，换个问题"))
    with TestClient(create_app(model=model, checkpointer_conf=MEMORY)) as c:
        tid = "U1001-0000abcd"
        config = {"configurable": {"thread_id": tid}}
        agent = c.app.state.agent
        # 阶段 4 起权限查会话表：直接造的 thread_id 要先在会话表里登记，否则 404
        c.portal.call(c.app.state.threads.create, tid, "U1001", "回不了充电座")
        # 造出「停在工具执行中」的存档：模型请求了工具，但还没有工具结果（和 stop_probe.py 里实测的一样）
        dangling = call("search_knowledge", {"query": "回不了充电座"}, call_id="s1")
        # portal.call：在 TestClient 后台的事件循环里执行异步函数
        c.portal.call(agent.aupdate_state, config, {"messages": [HumanMessage("回不了充电座"), dangling]}, "model")
        r, events = stream(c, "算了，换个问题", thread_id=tid)
    assert r.status_code == 200 and events[-1][1]["status"] == "completed"
    seen = model.received[-1]  # 模型这次收到的全部消息
    i = next(k for k, m in enumerate(seen) if isinstance(m, AIMessage) and m.tool_calls)
    # 请求工具的 AIMessage 后面紧跟着补上的 ToolMessage，然后才是新的一句话
    assert isinstance(seen[i + 1], ToolMessage) and seen[i + 1].tool_call_id == "s1"
    assert "停止" in str(seen[i + 1].content)
    assert isinstance(seen[i + 2], HumanMessage) and seen[i + 2].content == "算了，换个问题"
