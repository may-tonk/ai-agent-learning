"""
【v2 网页版新增 · 阶段 5】会话小结接口（routers/summary.py）和消息链接口（routers/threads.py 的 /chain）

小结用的是结构化输出：with_structured_output(ServiceSummary) 会把 ServiceSummary 当成一个「工具」让模型调用。
所以假模型只要返回 call("ServiceSummary", {...字段...})，就等于「模型按格式填好了小结」（见 tests/fakes.py 的 bind_tools）。
检查的是：
    生成 / 读取：存进小结表，打开会话能读回来；之后又聊了几句 → stale（过期）
    出错      ：模型乱填字段、或者不按格式返回 → 502，什么都不保存；对话为空 → 400
    权限、删除：别人的会话 403；删除会话时小结一起删
    对话稿    ：知识库原文不发给模型、工具结果截断、摘要消息单独标出
    消息链    ：AIMessage 的 tool_calls[].id 和 ToolMessage 的 tool_call_id 对得上
"""
import uuid

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from services.summary_service import _render_transcript
from tests.fakes import answer, call, scripted
from webapp.backend.app import create_app
from webapp.backend.tests.test_api_stream import LI, MEMORY, ZHANG, stream

# 一份合法的小结（字段和取值范围见 agent/schemas.py 的 ServiceSummary）
GOOD = {
    "user_intent": "查询自己有哪些订单",
    "category": "订单物流",
    "related_orders": [],
    "ticket_ids": [],
    "resolved": True,
    "satisfaction_risk": "低",
    "follow_up": "无",
}


def summary_url(tid):
    return f"/api/threads/{tid}/summary"


def test_generate_then_read_then_stale():
    model = scripted(call("list_my_orders", {}), answer("您有三个订单"), call("ServiceSummary", GOOD), answer("不客气"))
    with TestClient(create_app(model=model, checkpointer_conf=MEMORY)) as c:
        _, events = stream(c, "我有哪些订单")
        tid = events[0][1]["thread_id"]
        before = c.get(summary_url(tid), headers=ZHANG)
        created = c.post(summary_url(tid), headers=ZHANG).json()
        reopened = c.get(summary_url(tid), headers=ZHANG).json()
        stream(c, "谢谢", thread_id=tid)  # 生成小结之后又聊了一句
        later = c.get(summary_url(tid), headers=ZHANG).json()

    assert before.status_code == 200 and before.json() is None  # 还没生成过：200 + null，不是 404
    assert created["summary"] == GOOD
    assert created["message_count"] == 2 and created["stale"] is False  # 生成时消息表里 2 条：用户 + 客服
    assert reopened == created  # 打开会话时读回来的和生成时的一样
    assert later["stale"] is True and later["summary"] == GOOD  # 之后有新消息 → 过期，但旧小结还在

    # 第 3 次模型调用就是小结：[质检员提示词, 对话稿]，对话稿里有工具调用和工具结果
    transcript = model.received[2][1].content
    assert "用户：我有哪些订单" in transcript
    assert "客服调用工具：list_my_orders" in transcript and "工具结果（list_my_orders）" in transcript


def test_bad_output_is_502_and_nothing_saved():
    model = scripted(
        answer("您好"),
        call("ServiceSummary", {**GOOD, "category": "随便填的分类"}),  # 不在 Literal 可选值里 → Pydantic 校验失败
        answer("我不想按格式填"),  # 根本没调用 ServiceSummary → 结构化输出返回 None
    )
    with TestClient(create_app(model=model, checkpointer_conf=MEMORY)) as c:
        _, events = stream(c, "你好")
        tid = events[0][1]["thread_id"]
        invalid = c.post(summary_url(tid), headers=ZHANG)
        no_call = c.post(summary_url(tid), headers=ZHANG)
        saved = c.get(summary_url(tid), headers=ZHANG).json()
    assert invalid.status_code == 502 and "格式不对" in invalid.json()["detail"]
    assert no_call.status_code == 502 and "没有按格式" in no_call.json()["detail"]
    assert saved is None  # 失败时不保存


def test_empty_conversation_is_400():
    model = scripted()  # 不会调用模型：对话为空时在调用之前就拦下了
    with TestClient(create_app(model=model, checkpointer_conf=MEMORY)) as c:
        tid = f"U1001-{uuid.uuid4().hex[:8]}"
        c.portal.call(c.app.state.threads.create, tid, "U1001", "空会话")  # 只登记会话，不发消息
        r = c.post(summary_url(tid), headers=ZHANG)
    assert r.status_code == 400 and "还没有内容" in r.json()["detail"]
    assert model.received == []


def test_permissions_and_delete():
    model = scripted(answer("您好"), call("ServiceSummary", GOOD))
    with TestClient(create_app(model=model, checkpointer_conf=MEMORY)) as c:
        _, events = stream(c, "你好")
        tid = events[0][1]["thread_id"]
        assert c.post(summary_url(tid), headers=LI).status_code == 403  # 李四不能给张三的会话生成小结
        assert c.post(summary_url(tid), headers=ZHANG).status_code == 200
        assert c.get(summary_url(tid), headers=LI).status_code == 403
        c.delete(f"/api/threads/{tid}", headers=ZHANG)
        left = c.portal.call(c.app.state.summaries.get, tid)  # 直接查小结表
    assert left is None  # 删除会话时小结一起删了


def test_transcript_omits_knowledge_and_marks_summary():
    messages = [
        HumanMessage("Here is a summary of the conversation to date:\n\n用户之前问过订单", additional_kwargs={"lc_source": "summarization"}),
        HumanMessage("回不了充电座怎么办"),
        AIMessage("", tool_calls=[{"name": "search_knowledge", "args": {"query": "回充"}, "id": "k1"}]),
        ToolMessage("说明书原文" * 200, tool_call_id="k1", name="search_knowledge"),
        AIMessage("", tool_calls=[{"name": "get_order_detail", "args": {"order_id": "O1"}, "id": "o1"}]),
        ToolMessage("订" * 1000, tool_call_id="o1", name="get_order_detail"),
        AIMessage("请先清洁充电触点"),
    ]
    text = _render_transcript(messages)
    assert text.startswith("（较早的对话已压缩成摘要）")  # 摘要不当成「用户：」
    assert "说明书原文" not in text and "检索到知识库资料（原文略）" in text
    assert "订" * 300 in text and "订" * 301 not in text  # 其他工具结果截到 300 字
    assert text.endswith("客服：请先清洁充电触点")


def test_chain_links_tool_calls_to_results():
    model = scripted(call("list_my_orders", {}, call_id="c1"), answer("您有三个订单"))
    with TestClient(create_app(model=model, checkpointer_conf=MEMORY)) as c:
        _, events = stream(c, "我有哪些订单")
        tid = events[0][1]["thread_id"]
        chain = c.get(f"/api/threads/{tid}/chain", headers=ZHANG).json()
        other = c.get(f"/api/threads/{tid}/chain", headers=LI)
    # 页面上 2 个气泡，消息链里 4 条：用户 → 请求工具 → 工具结果 → 最终回答
    assert [m["type"] for m in chain] == ["human", "ai", "tool", "ai"]
    assert chain[1]["tool_calls"] == [{"id": "c1", "name": "list_my_orders", "args": {}}]
    assert chain[2]["tool_call_id"] == "c1" and chain[2]["tool_name"] == "list_my_orders" and chain[2]["status"] == "success"
    assert chain[3]["text"] == "您有三个订单"
    assert other.status_code == 403
