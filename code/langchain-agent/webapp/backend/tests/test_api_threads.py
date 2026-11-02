"""
【v2 网页版新增 · 阶段 4】会话接口（routers/threads.py）和消息记录

和前面的测试一样用假模型固定模型输出，检查的是：
    列表  ：发第一句话就建会话，标题 = 第一句话；只看得到自己的会话
    历史  ：用户的话和客服的回答（工具、参考资料）都记下来了，形状和前端 MessageBubble 一致
    审批  ：停在审批上时历史里带着 pending（刷新后卡片还在）；审批后同一条消息变成「决定 + 回答」
    重启  ：SQLite 文件里的会话和历史，后端重启后还在（方案里阶段 4 的完成标志）
    权限  ：别人的会话 403、不存在的 404
    删除  ：会话表、消息表、checkpointer 存档都删掉，之后再用这个 thread_id 是 404
「停止之后消息表里也有记录」要连真实后端点停止才能验证，见 webapp/scripts/approval_probe.py stop
"""
from fastapi.testclient import TestClient

from tests.fakes import answer, call, scripted
from webapp.backend.app import create_app
from webapp.backend.tests.test_api_resume import TICKET_ARGS, resume
from webapp.backend.tests.test_api_stream import LI, MEMORY, ZHANG, stream


def test_thread_is_created_and_listed_for_owner_only():
    model = scripted(answer("您好"), answer("好的"))
    with TestClient(create_app(model=model, checkpointer_conf=MEMORY)) as c:
        _, events = stream(c, "  我的扫地机器人\n回不了充电座，怎么办？这句话很长很长很长很长很长很长很长")
        tid = events[0][1]["thread_id"]
        stream(c, "第二句", thread_id=tid)
        mine = c.get("/api/threads", headers=ZHANG).json()
        others = c.get("/api/threads", headers=LI).json()
    assert [t["thread_id"] for t in mine] == [tid]  # 发了两句话，还是同一个会话
    assert mine[0]["title"] == "我的扫地机器人 回不了充电座，怎么办？这句话很长很长很长很长"  # 换行变空格，截到 30 个字
    assert others == []  # 李四看不到张三的会话


def test_history_has_user_and_assistant_messages():
    model = scripted(call("list_my_orders", {}), answer("您有三个订单"))
    with TestClient(create_app(model=model, checkpointer_conf=MEMORY)) as c:
        _, events = stream(c, "我有哪些订单")
        tid = events[0][1]["thread_id"]
        history = c.get(f"/api/threads/{tid}/messages", headers=ZHANG).json()
        state = c.get(f"/api/threads/{tid}/state", headers=ZHANG).json()
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["text"] == "我有哪些订单"
    bot = history[1]
    assert bot["text"] == "您有三个订单"
    assert [(t["name"], t["status"]) for t in bot["tools"]] == [("list_my_orders", "ok")]
    assert bot["pending"] == [] and bot["stopped"] is False and bot["error"] is None
    # 存档里：用户的话、请求工具的 AIMessage、工具结果、最终回答 = 4 条（页面上只有 2 个气泡）
    assert state["memory_messages"] == 4
    assert state["token_usage"]["model_calls"] == 2


def test_pending_approval_survives_in_history_then_becomes_decision():
    model = scripted(call("create_repair_ticket", TICKET_ARGS, call_id="t1"), answer("已为您创建报修单"))
    with TestClient(create_app(model=model, checkpointer_conf=MEMORY)) as c:
        _, first = stream(c, "帮我报修")
        tid = first[0][1]["thread_id"]
        before = c.get(f"/api/threads/{tid}/messages", headers=ZHANG).json()
        resume(c, tid, approved=True)
        after = c.get(f"/api/threads/{tid}/messages", headers=ZHANG).json()
    # 停在审批上：客服消息带着待审批的操作 → 刷新页面后审批卡片还在
    assert [p["name"] for p in before[1]["pending"]] == ["create_repair_ticket"]
    # 审批后：还是那 2 条消息（没有多出一条），客服消息里变成「已批准」的记录 + 工具 + 回答
    assert len(after) == 2 and after[1]["id"] == before[1]["id"]
    bot = after[1]
    assert bot["pending"] == []
    assert bot["decision"]["approved"] is True and bot["decision"]["items"][0]["name"] == "create_repair_ticket"
    assert [t["status"] for t in bot["tools"]] == ["ok"]
    assert bot["text"] == "已为您创建报修单"


def test_threads_and_history_survive_restart(tmp_path):
    conf = {"kind": "sqlite", "sqlite_path": str(tmp_path / "app.db")}
    with TestClient(create_app(model=scripted(answer("您好")), checkpointer_conf=conf)) as c:
        _, events = stream(c, "你好")
        tid = events[0][1]["thread_id"]
    # 第一个 with 结束 = 后端关闭；再用同一个文件建一个新的后端 = 重启
    with TestClient(create_app(model=scripted(answer("再见")), checkpointer_conf=conf)) as c:
        threads = c.get("/api/threads", headers=ZHANG).json()
        history = c.get(f"/api/threads/{tid}/messages", headers=ZHANG).json()
    assert [t["thread_id"] for t in threads] == [tid]
    assert [m["text"] for m in history] == ["你好", "您好"]


def test_permissions():
    with TestClient(create_app(model=scripted(answer("您好")), checkpointer_conf=MEMORY)) as c:
        _, events = stream(c, "你好")
        tid = events[0][1]["thread_id"]
        assert c.get(f"/api/threads/{tid}/messages", headers=LI).status_code == 403
        assert c.get(f"/api/threads/{tid}/state", headers=LI).status_code == 403
        assert c.delete(f"/api/threads/{tid}", headers=LI).status_code == 403
        assert c.get("/api/threads/U1001-00000000/messages", headers=ZHANG).status_code == 404
        r, _ = stream(c, "你好", thread_id="U1001-00000000")
        assert r.status_code == 404  # 发消息时带一个不存在的会话也是 404
        assert c.get("/api/threads/bad id/messages", headers=ZHANG).status_code == 422  # 格式不对


def test_delete_removes_everything():
    with TestClient(create_app(model=scripted(answer("您好")), checkpointer_conf=MEMORY)) as c:
        _, events = stream(c, "你好")
        tid = events[0][1]["thread_id"]
        config = {"configurable": {"thread_id": tid}}
        assert c.delete(f"/api/threads/{tid}", headers=ZHANG).status_code == 204
        snapshot = c.portal.call(c.app.state.agent.aget_state, config)
        listed = c.get("/api/threads", headers=ZHANG).json()
        history = c.get(f"/api/threads/{tid}/messages", headers=ZHANG)
        rows = c.portal.call(c.app.state.messages.list_by_thread, tid)
    assert snapshot.values == {}  # checkpointer 存档没了
    assert listed == [] and history.status_code == 404  # 会话表没了
    assert rows == []  # 消息表也没了
