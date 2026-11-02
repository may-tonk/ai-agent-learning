"""
检索 + 重排测试：用假的向量库和假的重排模型，检查「召回 → 重排 → 截断 → 过滤」这条流程
不需要 Chroma、不需要 API key、不联网、不花钱。

假向量库：按固定顺序返回 10 条候选（距离 0.1, 0.2, …, 1.0）
假重排器：按我们事先写好的分数排序，模拟「向量检索排第 6 的那条，其实最相关」
"""
import pytest
from langchain_core.documents import Document

from services import kb_service, rerank_service

CANDIDATES = [(Document(page_content=f"资料{i}", metadata={"file_name": f"f{i}.txt"}), round(0.1 * i, 1)) for i in range(1, 11)]


class FakeVectorStore:
    def __init__(self):
        self.asked_k = None

    def similarity_search_with_score(self, query, k):
        self.asked_k = k  # 记下被要求召回几条
        return CANDIDATES[:k]


class FakeReranker:
    """scores：{资料原文: 分数}；没写到的资料分数为 0。和 DashScopeRerank.rerank 一样按分数从高到低返回"""

    def __init__(self, scores=None, fail=False):
        self.scores = scores or {}
        self.fail = fail

    def rerank(self, documents, query, top_n):
        if self.fail:
            raise AttributeError("'NoneType' object has no attribute 'results'")  # 模拟接口报错时 DashScopeRerank 的表现
        scored = [{"index": i, "relevance_score": self.scores.get(d, 0.0)} for i, d in enumerate(documents)]
        return sorted(scored, key=lambda r: r["relevance_score"], reverse=True)[:top_n]


@pytest.fixture
def store(monkeypatch):
    fake = FakeVectorStore()
    monkeypatch.setattr(kb_service, "_get_vector_store", lambda: fake)
    monkeypatch.setitem(kb_service.chroma_conf, "k", 3)
    monkeypatch.setitem(kb_service.chroma_conf, "max_distance", 1.2)
    monkeypatch.setitem(kb_service.chroma_conf, "rerank", {"enabled": True, "fetch_k": 10, "min_score": 0.1})
    return fake


def use_reranker(monkeypatch, reranker):
    monkeypatch.setattr(rerank_service, "get_reranker", lambda: reranker)


def test_rerank_recalls_10_and_keeps_best_3(store, monkeypatch):
    use_reranker(monkeypatch, FakeReranker({"资料6": 0.9, "资料1": 0.8, "资料2": 0.5}))
    hits = kb_service.search("迷路怎么办")
    assert store.asked_k == 10                                   # 召回了 fetch_k 条
    assert [h["content"] for h in hits] == ["资料6", "资料1", "资料2"]   # 按重排分数排序，只留 k 条
    assert [h["vector_rank"] for h in hits] == [6, 1, 2]          # 向量检索排第 6 的被提到了第 1
    assert hits[0]["rerank_score"] == 0.9 and hits[0]["source"] == "f6.txt"


def test_min_score_drops_irrelevant(store, monkeypatch):
    use_reranker(monkeypatch, FakeReranker({"资料3": 0.6, "资料4": 0.05}))  # 只有 1 条够分
    hits = kb_service.search("今天天气怎么样")
    assert [h["content"] for h in hits] == ["资料3"]


def test_all_below_min_score_returns_empty(store, monkeypatch):
    use_reranker(monkeypatch, FakeReranker({}))  # 全部 0 分
    assert kb_service.search("写一首诗") == []


def test_rerank_failure_falls_back_to_vector_order(store, monkeypatch):
    use_reranker(monkeypatch, FakeReranker(fail=True))
    seen = []  # 【阶段 6】进度里也要如实说「重排失败」
    hits = kb_service.search("迷路怎么办", on_progress=lambda *a: seen.append(a))
    assert [h["content"] for h in hits] == ["资料1", "资料2", "资料3"]  # 退回向量检索前 3 条，不报错
    assert "rerank_score" not in hits[0]
    assert seen[-1][2].startswith("重排失败，按向量检索顺序取前 3 条")


def test_rerank_disabled_is_old_behavior(store, monkeypatch):
    monkeypatch.setitem(kb_service.chroma_conf, "rerank", {"enabled": False, "fetch_k": 10})
    use_reranker(monkeypatch, FakeReranker(fail=True))  # 关掉时根本不应该调用重排
    hits = kb_service.search("迷路怎么办")
    assert store.asked_k == 3
    assert [h["content"] for h in hits] == ["资料1", "资料2", "资料3"]


def test_max_distance_still_prefilters(store, monkeypatch):
    monkeypatch.setitem(kb_service.chroma_conf, "max_distance", 0.25)  # 只有距离 0.1、0.2 的两条能进重排
    reranker = FakeReranker({"资料6": 0.9, "资料2": 0.7, "资料1": 0.6})
    use_reranker(monkeypatch, reranker)
    hits = kb_service.search("迷路怎么办")
    assert [h["content"] for h in hits] == ["资料2", "资料1"]


def test_fetch_k_never_smaller_than_k(store, monkeypatch):
    monkeypatch.setitem(kb_service.chroma_conf, "rerank", {"enabled": True, "fetch_k": 2, "min_score": None})
    use_reranker(monkeypatch, FakeReranker({"资料3": 0.9}))
    kb_service.search("迷路怎么办")
    assert store.asked_k == 3  # fetch_k 配小了，也至少召回 k 条


def test_progress_callback_reports_each_step(store, monkeypatch):
    """【v2 网页版 · 阶段 6】on_progress：每一步先报 running、再报 done；不传回调时行为和以前一样（上面的测试都没传）"""
    use_reranker(monkeypatch, FakeReranker({"资料6": 0.9, "资料1": 0.8, "资料2": 0.5}))
    seen = []
    kb_service.search("迷路怎么办", on_progress=lambda step, status, message: seen.append((step, status, message)))
    assert [(s, st) for s, st, _ in seen] == [("recall", "running"), ("recall", "done"), ("rerank", "running"), ("rerank", "done")]
    assert seen[1][2].startswith("召回 10 条（")  # 没有被距离过滤掉的，不多说那半句
    assert seen[3][2].startswith("重排后保留 3 条，最高相关度 0.90（")


def test_progress_without_rerank_or_candidates(store, monkeypatch):
    """关掉重排、或者召回结果全被距离过滤掉时，只有召回这一步"""
    monkeypatch.setitem(kb_service.chroma_conf, "max_distance", 0.05)  # 10 条都比 0.05 远 → 全部丢掉
    seen = []
    assert kb_service.search("写一首诗", on_progress=lambda *a: seen.append(a)) == []
    assert [(s, st) for s, st, _ in seen] == [("recall", "running"), ("recall", "done")]
    assert "距离过滤后剩 0 条" in seen[1][2]
