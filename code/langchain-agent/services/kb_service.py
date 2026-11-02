"""
知识库检索：连实验6 在 Ubuntu 上建好的 Chroma（集合 agent），只读；检索 = 召回 + 重排 + 截断

和实验6 的区别：
- 实验6 的 rag_summarize 工具检索完还会再调一次模型做总结（一次工具调用花两次模型的钱），
  这里直接把检索到的原文片段交给 agent，让 agent 自己组织回答，少一次模型调用。
- 用 similarity_search_with_score 拿到「距离分数」，过滤掉不相关的结果，
  并把来源文件、分数一起返回，工具会把它们放进 ToolMessage.artifact 给程序用。
- 多了一步「重排」：先多召回一些（fetch_k=10），再用重排模型精排，只留最相关的 k=3 条（实验6 是直接取前 3 条）。

【检索的三步（search 函数）】
    ① 召回（粗筛）：问题 → 向量模型变成向量 → Chroma 找距离最近的 fetch_k 条（10 条）→ 先按 max_distance 丢掉明显无关的
    ② 重排（精排）：services/rerank_service.rerank → 百炼 gte-rerank-v2 给「问题 + 每条资料」打相关性分数，重新排序
    ③ 截断 + 过滤：只留前 k 条（3 条），并丢掉重排分数低于 min_score 的
    关掉重排（config/chroma.yml 的 rerank.enabled: false）时：直接取向量检索的前 k 条，和加重排之前完全一样

【几个容易混的概念】
    距离（distance）：向量检索给的分数，越小越像。本集合用 L2 距离（实验6 建集合时没指定，Chroma 默认 L2）
    相似度（similarity）：越大越像，和距离方向相反。LangChain 的 similarity_search_with_score 返回的是「距离」
    重排分数（rerank_score）：重排模型给的 0 ~ 1 分数，越大越相关；它比距离更可靠，所以最终的相关性过滤用它
    k：最后交给大模型几条；fetch_k：向量检索召回几条（必须 ≥ k，否则重排没有挑选的余地）

【在整体流程里的位置】RAG 的「检索」这一步（阶段：提问时）：
    模型决定调用 search_knowledge（agent/tools/kb_tools.py）→ 本文件 search() → 结果作为 ToolMessage 回到模型
    「入库 / 切片」那一步不在本项目，在实验6 的 rag/vector_store.py（切成约 150 字一块，共 335 块）
相关配置：config/chroma.yml（地址、集合名、k、max_distance、rerank 段）、config/model.yml 的 embedding 和 rerank 段、
          .env 的 CHROMA_HOST / DASHSCOPE_API_KEY

【v2 网页版 · 阶段 6】search() 多了一个可选参数 on_progress：每一步开始、结束时「报告」一次进度，
    网页上工具标签下面就会实时显示「向量检索中… → 召回 10 条（0.62 秒）→ 重排中… → 保留 3 条」。
    为什么是「传一个回调函数」，而不是在这里直接调用 LangGraph 的 get_stream_writer：
        services/ 是纯业务层，不应该知道自己是被 agent、网页还是测试调用的（errors.py 开头也是这个原则）。
        谁想要进度，谁就传一个函数进来：工具传「写进 LangGraph 流」的函数（agent/tools/kb_tools.py），
        测试传「记到列表里」的函数，不传就什么都不做 —— 和以前完全一样。
"""
import os
import time
from collections.abc import Callable
from functools import lru_cache

from services import rerank_service
from utils.config_handler import chroma_conf
from utils.logger_handler import logger


@lru_cache  # Chroma 连接只建一次；第一次用到知识库时才连接（没配 Chroma 也不影响其他功能）
def _get_vector_store():
    """
    创建并缓存 LangChain 的 Chroma 向量库对象。
    返回：langchain_chroma.Chroma
    异常：没配 CHROMA_HOST → RuntimeError；Chroma 连不上 → chromadb 抛的连接异常
         （都会被 agent/middleware.py 的 guard_tool_call 接住，变成「系统暂时无法完成」）
    注意：因为有 lru_cache，第一次连接失败后不会缓存（异常不缓存），下次检索会重新尝试连接
    """
    # 放在函数里导入：不用知识库时（如跑 lessons/03、tests）不需要加载 chromadb
    import chromadb
    from langchain_chroma import Chroma

    from model.factory import get_embeddings

    # 配置文件里的 host 优先，留空时用环境变量；端口则是环境变量优先
    host = chroma_conf.get("host") or os.getenv("CHROMA_HOST")
    port = int(os.getenv("CHROMA_PORT") or chroma_conf.get("port", 8000))
    if not host:
        raise RuntimeError("没有配置 Chroma 地址：请在 .env 里设置 CHROMA_HOST")

    logger.info(f"[知识库] 连接 Chroma {host}:{port}，集合 {chroma_conf['collection_name']}")
    # Chroma(...) 的参数：
    #   client             chromadb.HttpClient：连接远程 Chroma 服务（实验6 用 docker 跑在 Ubuntu 上）
    #                      本地文件版用的是 persist_directory=...，这里不是
    #   collection_name    集合名，必须和建库时一致
    #   embedding_function 检索时把「问题」变成向量用的模型，必须和建库时的模型、维度一致
    return Chroma(
        client=chromadb.HttpClient(host=host, port=port),
        collection_name=chroma_conf["collection_name"],
        embedding_function=get_embeddings(),
    )


# 【阶段 6】进度回调的样子：report(步骤, 状态, 给人看的一句话)
#   步骤：recall（召回）/ rerank（重排）；状态：running（开始）/ done（完成）
#   同一个步骤先报 running、再报 done，前端按「步骤」更新同一行（不是追加一行）
ProgressCallback = Callable[[str, str, str], None]


def search(query: str, k: int | None = None, on_progress: ProgressCallback | None = None) -> list[dict]:
    """
    检索知识库：召回 → 重排 → 截断，返回最相关的最多 k 条资料。

    参数：
        query：检索用的问题（模型改写过的，比如「扫地机器人总是迷路 导航异常 重新建图 解决方法」）
        k：最后最多返回几条；不传用 config/chroma.yml 的 k（当前 3）
        on_progress：【阶段 6】进度回调，见上面的 ProgressCallback；不传 = 不报告进度
    返回：[{"content": 原文片段, "source": 来源文件, "distance": 向量距离,
            "vector_rank": 向量检索里排第几, "rerank_score": 重排分数}, ...]
          开了重排时按 rerank_score 从高到低排；没开重排时按 distance 从近到远排，也没有后两个字段
          可能少于 k 条，也可能是空列表（工具层会告诉模型「没找到，不要编造」）
    谁调用：agent/tools/kb_tools.py 的 search_knowledge；返回的整个列表会放进 ToolMessage.artifact，
            main.py 用其中的 source 显示「参考资料」
    """
    k = k or chroma_conf["k"]
    max_distance = chroma_conf.get("max_distance")
    rerank_conf = chroma_conf.get("rerank") or {}
    use_rerank = rerank_conf.get("enabled", False)
    # 开重排时多召回一些给重排模型挑；max(…, k) 保证召回数不少于最终要的条数
    fetch_k = max(rerank_conf.get("fetch_k", k), k) if use_rerank else k
    # 【阶段 6】没传回调时用一个「什么都不做」的函数，下面就不用每次都写 if on_progress
    report = on_progress or (lambda step, status, message: None)

    # ---------- ① 召回（粗筛） ----------
    report("recall", "running", f"向量检索中（召回 {fetch_k} 条）…")
    # perf_counter：专门用来计时的时钟（精度高、不受系统改时间影响），两次相减就是用了几秒
    start = time.perf_counter()
    # similarity_search_with_score(query, k)：
    #   先用 embedding_function 把 query 变成向量，再在集合里找最近的 k 个文本块
    #   返回 [(Document, 距离), ...]，按距离从小到大排好；Document.page_content 是原文，.metadata 是建库时存的来源等信息
    #   这里的分数是「距离」，越小越像；和「相似度」（越大越像）方向相反，别搞反
    #   距离的算法（L2 / cosine）由实验6 建集合时决定（Chroma 默认 L2），所以 max_distance 要按实测分布来定
    #   （对比：similarity_search 只返回 Document 不带分数，没法做阈值过滤）
    results = _get_vector_store().similarity_search_with_score(query, k=fetch_k)

    candidates = []
    for doc, distance in results:
        if max_distance is not None and distance > max_distance:
            # DEBUG 级别只写进日志文件，不显示在控制台；调 max_distance 时可以去 logs/ 里看被丢掉的分数
            logger.debug(f"[知识库] 丢弃不相关结果 distance={distance:.3f}")
            continue
        candidates.append(
            {
                "content": doc.page_content,
                # 来源文件名在 metadata 里：兼容 file_name 和 source 两种键名（取决于建库时怎么存的）
                "source": doc.metadata.get("file_name") or doc.metadata.get("source", "未知"),
                "distance": round(float(distance), 4),
            }
        )
    # 【阶段 6】召回完成。距离过滤丢掉了一些时才多说一句，平时就是「召回 10 条（0.62 秒）」
    dropped = f"，距离过滤后剩 {len(candidates)} 条" if len(candidates) < len(results) else ""
    report("recall", "done", f"召回 {len(results)} 条{dropped}（{time.perf_counter() - start:.2f} 秒）")

    # ---------- ② 重排（精排）+ ③ 截断 ----------
    if use_rerank and candidates:
        report("rerank", "running", f"重排中（{len(candidates)} 条）…")
        start = time.perf_counter()
        hits = rerank_service.rerank(query, candidates, top_n=k, min_score=rerank_conf.get("min_score"))
        secs = f"（{time.perf_counter() - start:.2f} 秒）"
        if hits and "rerank_score" not in hits[0]:
            # 重排接口出错时 rerank_service 会退回向量检索的顺序，结果里没有 rerank_score（见 rerank_service.py）
            report("rerank", "done", f"重排失败，按向量检索顺序取前 {len(hits)} 条{secs}")
        else:
            best = f"，最高相关度 {hits[0]['rerank_score']:.2f}" if hits else "，都不相关"
            report("rerank", "done", f"重排后保留 {len(hits)} 条{best}{secs}")
    else:
        # 没开重排、或者召回结果全被距离过滤掉了（没东西可排）：直接截断，不报告重排这一步
        hits = candidates[:k]

    # 例：「召回 10 条，距离过滤后 10 条，最终 3 条」；关掉重排时召回数就等于 k
    logger.info(f"[知识库] 检索「{query}」召回 {len(results)} 条，距离过滤后 {len(candidates)} 条，最终 {len(hits)} 条")
    return hits
