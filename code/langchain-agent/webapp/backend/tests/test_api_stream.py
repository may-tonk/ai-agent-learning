"""
【v2 网页版新增 · 阶段 2】POST /api/chat/stream 流式接口测试

和 test_api_chat.py 一样用假模型固定模型输出，检查的是「事件顺序是否符合协议」（streaming/protocol.py）：
    普通问答：run_started → token… → done(completed)
    调工具  ：run_started → tool_started → tool_finished → token… → done(completed)
    工具出错：tool_finished 的 ok=False，后面照常 done
    审批    ：… → approval_required → done(interrupted)，再发消息 → 409
    模型出错：… → error → done(error)，不会卡住
    记忆    ：同一个 thread_id 连问两次，第二次模型能看到第一次的消息
「是不是真的一个字一个字到达」这件事假模型测不出来（它一次给出整段话），
由 webapp/scripts/sse_probe.py 连真实 DeepSeek 看每条事件的到达时间来验证。
"""
import json

from fastapi.testclient import TestClient

from tests.fakes import answer, call, scripted
from webapp.backend.app import create_app

MEMORY = {"kind": "memory"}
ZHANG = {"X-User-Id": "U1001"}
LI = {"X-User-Id": "U1002"}


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """
    把 SSE 响应文本解析成 [(事件名, 数据), ...]。
    格式：每条事件是「event: xxx\\ndata: {...}」，事件之间用空行分隔（和前端 src/api/sse.js 的解析逻辑相同）
    """
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((fields["event"], json.loads(fields["data"])))
    return events


def stream(client, message, headers=ZHANG, thread_id=None):
    """发一次流式请求，返回 (响应, 事件列表)。TestClient 会等响应全部结束才返回，正好拿到完整的事件序列"""
    r = client.post("/api/chat/stream", json={"thread_id": thread_id, "message": message}, headers=headers)
    return r, (parse_sse(r.text) if r.status_code == 200 else [])


def names(events):
    """只看事件名，连续的 token 合并成一个，方便和协议里的顺序比较"""
    out = []
    for name, _ in events:
        if not (name == "token" and out and out[-1] == "token"):
            out.append(name)
    return out


def test_plain_answer_streams_tokens_then_done():
    with TestClient(create_app(model=scripted(answer("您好，请问有什么可以帮您？")), checkpointer_conf=MEMORY)) as c:
        r, events = stream(c, "你好")
    assert r.headers["content-type"].startswith("text/event-stream")
    assert names(events) == ["run_started", "token", "done"]
    text = "".join(d["text"] for n, d in events if n == "token")
    assert text == "您好，请问有什么可以帮您？"
    done = events[-1][1]
    assert done["status"] == "completed"
    assert done["answer"] == text  # done 里的最终回答和流出来的文字一致
    assert done["thread_id"] == events[0][1]["thread_id"]
    assert done["token_usage"]["total_tokens"] == 190


def test_tool_events_come_between_model_calls():
    model = scripted(call("list_my_orders", {}), answer("您有三个订单"))
    with TestClient(create_app(model=model, checkpointer_conf=MEMORY)) as c:
        _, events = stream(c, "我有哪些订单")
    assert names(events) == ["run_started", "tool_started", "tool_finished", "token", "done"]
    started, finished = events[1][1], events[2][1]
    assert started["name"] == "list_my_orders"
    # 开始和结束靠 id 配对；tool-finished 原始事件里没有工具名，是 runner 记下来补上的
    assert finished["id"] == started["id"] and finished["name"] == "list_my_orders" and finished["ok"] is True
    # 最终回答的文字来自第 2 次模型调用，前端靠 call 判断「换了一次调用，清空重来」
    assert {d["call"] for n, d in events if n == "token"} == {2}
    assert [t["name"] for t in events[-1][1]["tool_calls"]] == ["list_my_orders"]


def test_command_tool_and_failed_tool():
    """get_order_detail 返回 Command（ToolMessage 藏在 update 里）；订单不存在时工具出错，ok=False 但流程照常结束"""
    model = scripted(
        call("get_order_detail", {"order_id": "SO20260312"}, call_id="c1"),
        call("get_order_detail", {"order_id": "SO20990101"}, call_id="c2"),
        answer("第二个订单号查不到"),
    )
    with TestClient(create_app(model=model, checkpointer_conf=MEMORY)) as c:
        _, events = stream(c, "查两个订单")
    finished = {d["id"]: d["ok"] for n, d in events if n == "tool_finished"}
    assert finished == {"c1": True, "c2": False}
    assert events[-1][1]["status"] == "completed"


def test_approval_ends_with_interrupted_and_blocks_next_message():
    args = {"order_id": "SO20260312", "fault_category": "拖地漏水", "description": "拖地时一直漏水"}
    with TestClient(create_app(model=scripted(call("create_repair_ticket", args)), checkpointer_conf=MEMORY)) as c:
        _, events = stream(c, "报修")
        r, _ = stream(c, "好了吗", thread_id=events[0][1]["thread_id"])
    assert names(events)[-2:] == ["approval_required", "done"]
    assert events[-2][1]["pending"][0]["name"] == "create_repair_ticket"
    assert events[-1][1]["status"] == "interrupted"
    assert r.status_code == 409  # 开始推流之前的检查，照常返回 HTTP 状态码


def test_model_failure_becomes_error_event_not_a_hang():
    # 剧本是空的：模型一被调用就抛 RuntimeError（模拟意外错误）
    with TestClient(create_app(model=scripted(), checkpointer_conf=MEMORY)) as c:
        r, events = stream(c, "你好")
    assert r.status_code == 200  # 开始推流后出错，状态码已经是 200 了
    assert names(events) == ["run_started", "error", "done"]
    assert events[-1][1]["status"] == "error"
    assert "RuntimeError" not in events[1][1]["message"]  # 内部细节不给前端


def test_stream_remembers_and_checks_owner():
    model = scripted(answer("好的"), answer("您刚才说的是 SO20260312"))
    with TestClient(create_app(model=model, checkpointer_conf=MEMORY)) as c:
        _, events = stream(c, "我的订单是 SO20260312")
        tid = events[0][1]["thread_id"]
        stream(c, "我刚才说的订单号是多少", thread_id=tid)
        r, _ = stream(c, "偷看", headers=LI, thread_id=tid)
    assert any("SO20260312" in str(m.content) for m in model.received[-1])
    assert r.status_code == 403
