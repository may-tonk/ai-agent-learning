"""
【v2 网页版新增 · 阶段 6】工具进度：检索知识库时，进度通过 tool_progress 事件实时推给浏览器

用假模型（tests/fakes.py）+ 假向量库、假重排器（tests/test_kb_rerank.py），不连 Chroma、不花钱。检查的是：
    流式  ：tool_progress 出现在 tool_started 和 tool_finished 之间，id 对得上，顺序是 召回 → 重排，每步 running → done
    记录  ：存进消息表的工具标签带着最终进度（同一步骤只留一行），刷新后能显示回来
    不流式：POST /api/chat 用的是 ainvoke，没人订阅 custom 流 —— 工具里照样调用 get_stream_writer，不能出错
"""
import pytest
from fastapi.testclient import TestClient

from services import kb_service, rerank_service
from tests.fakes import answer, call, scripted
from tests.test_kb_rerank import FakeReranker, FakeVectorStore
from webapp.backend.app import create_app
from webapp.backend.tests.test_api_stream import MEMORY, ZHANG, stream


@pytest.fixture(autouse=True)
def fake_kb(monkeypatch):
    """假向量库返回 10 条候选，假重排器把「资料6」排第一；配置和真实的 chroma.yml 一样：召回 10、留 3"""
    monkeypatch.setattr(kb_service, "_get_vector_store", lambda: FakeVectorStore())
    monkeypatch.setitem(kb_service.chroma_conf, "k", 3)
    monkeypatch.setitem(kb_service.chroma_conf, "max_distance", 1.2)
    monkeypatch.setitem(kb_service.chroma_conf, "rerank", {"enabled": True, "fetch_k": 10, "min_score": 0.1})
    monkeypatch.setattr(rerank_service, "get_reranker", lambda: FakeReranker({"资料6": 0.9, "资料1": 0.8, "资料2": 0.5}))


def search_then_answer():
    return scripted(call("search_knowledge", {"query": "迷路怎么办"}, call_id="k1"), answer("请重新建图"))


def test_progress_events_stream_between_tool_start_and_finish():
    with TestClient(create_app(model=search_then_answer(), checkpointer_conf=MEMORY)) as c:
        _, events = stream(c, "扫地机器人总是迷路怎么办")
    names = [n for n, _ in events]
    start, finish = names.index("tool_started"), names.index("tool_finished")
    progress = [d for n, d in events if n == "tool_progress"]
    # 全部进度都在「工具开始」和「工具结束」之间
    assert all(start < i < finish for i, n in enumerate(names) if n == "tool_progress")
    assert {d["id"] for d in progress} == {"k1"}  # 属于这次工具调用
    assert [(d["step"], d["status"]) for d in progress] == [
        ("recall", "running"), ("recall", "done"), ("rerank", "running"), ("rerank", "done"),
    ]
    assert progress[-1]["message"].startswith("重排后保留 3 条")
    assert events[-1][1]["status"] == "completed"


def test_progress_is_saved_with_the_tool():
    with TestClient(create_app(model=search_then_answer(), checkpointer_conf=MEMORY)) as c:
        _, events = stream(c, "扫地机器人总是迷路怎么办")
        tid = events[0][1]["thread_id"]
        history = c.get(f"/api/threads/{tid}/messages", headers=ZHANG).json()
    tool = history[1]["tools"][0]
    assert tool["name"] == "search_knowledge" and tool["status"] == "ok"
    # 同一个步骤只留一行，而且是最后的 done 状态（running 那条被替换掉了）
    assert [(p["step"], p["status"]) for p in tool["progress"]] == [("recall", "done"), ("rerank", "done")]


def test_non_stream_chat_still_works_without_custom_subscriber():
    with TestClient(create_app(model=search_then_answer(), checkpointer_conf=MEMORY)) as c:
        r = c.post("/api/chat", json={"message": "扫地机器人总是迷路怎么办"}, headers=ZHANG)
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "请重新建图" and body["sources"] == ["f6.txt", "f1.txt", "f2.txt"]
