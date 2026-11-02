"""
【v2 网页版新增】/api/chat 接口测试（阶段 1）

用假模型（tests/fakes.py 的剧本模型）固定模型输出，只检查「后端这一侧」的行为：
    接口能不能通、thread_id 怎么生成、记忆是否生效、权限和审批的拦截、SQLite 重启后记忆还在
不需要 API key，不联网，几秒跑完。

TestClient：FastAPI 自带的测试客户端，不用真的启动 uvicorn，直接在进程里发 HTTP 请求。
用 with TestClient(app) as client: 的写法时，会执行 app 的 lifespan（打开 checkpointer、建 agent），
退出 with 时执行关闭逻辑 —— 和真实启动、关闭后端完全一样。
"""
from fastapi.testclient import TestClient

from tests.fakes import answer, call, scripted
from webapp.backend.app import create_app

MEMORY = {"kind": "memory"}
ZHANG = {"X-User-Id": "U1001"}
LI = {"X-User-Id": "U1002"}


def test_new_chat_returns_answer_and_thread_id():
    with TestClient(create_app(model=scripted(answer("您好，请问有什么可以帮您？")), checkpointer_conf=MEMORY)) as c:
        r = c.post("/api/chat", json={"message": "你好"}, headers=ZHANG)
    assert r.status_code == 200
    body = r.json()
    assert body["thread_id"].startswith("U1001-")
    assert body["answer"] == "您好，请问有什么可以帮您？"
    assert body["token_usage"]["total_tokens"] == 190  # 来自 track_token_usage 中间件（异步也生效）


def test_same_thread_remembers_previous_turn():
    model = scripted(answer("好的"), answer("您刚才说的是 SO20260312"))
    with TestClient(create_app(model=model, checkpointer_conf=MEMORY)) as c:
        tid = c.post("/api/chat", json={"message": "我的订单是 SO20260312"}, headers=ZHANG).json()["thread_id"]
        c.post("/api/chat", json={"thread_id": tid, "message": "我刚才说的订单号是多少"}, headers=ZHANG)
    # 第二次调用模型时，消息里要有第一轮的问题 —— 证明 checkpointer 按 thread_id 把历史读出来了
    assert any("SO20260312" in str(m.content) for m in model.received[-1])


def test_tool_calls_are_reported_and_other_users_thread_is_forbidden():
    model = scripted(call("list_my_orders", {}), answer("您有两个订单"))
    with TestClient(create_app(model=model, checkpointer_conf=MEMORY)) as c:
        body = c.post("/api/chat", json={"message": "我有哪些订单"}, headers=ZHANG).json()
        r = c.post("/api/chat", json={"thread_id": body["thread_id"], "message": "偷看"}, headers=LI)
    assert [t["name"] for t in body["tool_calls"]] == ["list_my_orders"]  # 工具经过异步的 guard_tool_call
    assert body["answer"] == "您有两个订单"
    assert r.status_code == 403  # 李四不能用张三的 thread_id


def test_login_is_required():
    with TestClient(create_app(model=scripted(), checkpointer_conf=MEMORY)) as c:
        assert c.post("/api/chat", json={"message": "你好"}).status_code == 401
        assert c.post("/api/chat", json={"message": "你好"}, headers={"X-User-Id": "U0000"}).status_code == 401
        assert c.post("/api/chat", json={"message": ""}, headers=ZHANG).status_code == 422  # 空消息被校验拦下


def test_pending_approval_is_returned_and_blocks_new_message():
    args = {"order_id": "SO20260312", "fault_category": "拖地漏水", "description": "拖地时一直漏水"}
    with TestClient(create_app(model=scripted(call("create_repair_ticket", args)), checkpointer_conf=MEMORY)) as c:
        body = c.post("/api/chat", json={"message": "报修"}, headers=ZHANG).json()
        r = c.post("/api/chat", json={"thread_id": body["thread_id"], "message": "好了吗"}, headers=ZHANG)
    assert body["pending_approvals"][0]["name"] == "create_repair_ticket"
    assert r.status_code == 409  # 停在审批上的对话，不能直接接着发消息


def test_users_endpoint_hides_phone():
    with TestClient(create_app(model=scripted(), checkpointer_conf=MEMORY)) as c:
        users = c.get("/api/users").json()
    assert {u["user_id"] for u in users} == {"U1001", "U1002", "S9001"}
    assert all("phone" not in u for u in users)


def test_sqlite_memory_survives_restart(tmp_path):
    """阶段 1 的完成标志之一：关掉后端再启动，同一个 thread_id 还记得上一轮"""
    conf = {"kind": "sqlite", "sqlite_path": str(tmp_path / "app.db")}

    # 第一次「启动后端」：聊一句，然后退出 with = 关闭后端
    with TestClient(create_app(model=scripted(answer("好的")), checkpointer_conf=conf)) as c:
        tid = c.post("/api/chat", json={"message": "我的订单是 SO20260312"}, headers=ZHANG).json()["thread_id"]

    # 第二次「启动后端」：全新的 app、全新的模型对象，内存里什么都没有，只有 SQLite 文件还在
    model = scripted(answer("记得"))
    with TestClient(create_app(model=model, checkpointer_conf=conf)) as c:
        c.post("/api/chat", json={"thread_id": tid, "message": "我刚才说的订单号是多少"}, headers=ZHANG)
    assert any("SO20260312" in str(m.content) for m in model.received[-1])
