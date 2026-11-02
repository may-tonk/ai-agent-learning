"""
重排（rerank）：检索的第 2 步，给向量检索「召回」的候选资料重新打分、排序、截断

【为什么需要重排】
    向量检索是「粗筛」：问题和资料各自压成一个向量再比距离，速度极快，但会丢细节，排序不够准——
    真正最相关的那一条，经常排在第 4、第 5 名，只取前 3 条就会把它漏掉。
    重排是「精排」：把「问题 + 一条资料」放在一起交给重排模型整体读一遍，直接给出相关性分数，更准但更慢。
    所以两段式检索：向量检索多召回一些（如 10 条，宁多勿漏）→ 重排模型逐条打分 → 只留分数最高的 3 条给大模型。

【打个比方】招聘：向量检索像 HR 按关键词初筛简历，一次能筛几千份，先挑出 10 份；
             重排像面试官把这 10 份逐份细看，选出最合适的 3 个人。

【实测例子（2026-10-28，集合 agent，召回 10 条 → 重排留 3 条）】
    「扫地机器人总是迷路怎么办」：最终 3 条来自向量检索的第 [1, 7, 3] 名
        向量第 7 名「什么是 dToF 导航技术」被提到第 2（分数 0.31），向量第 2 名「清扫路线混乱」被挤到第 4（0.172）
    「机器人连不上WiFi」：最终来自第 [1, 2, 5] 名，向量第 5 名「工作时突然断网」被提进前 3（0.298）
    「今天天气怎么样」：10 条候选的分数全部 0.006 → 被 min_score=0.1 全部丢掉，最终 0 条
        （它的向量距离是 1.03，单靠 max_distance=1.2 拦不住，这正是加重排之前的老问题）
    ！注意：重排也不是绝对正确。「滤网多久换一次」里，向量第 1 名「尘盒滤网……6 个月更换一次」被重排挤到第 6，
        换上来的是「HEPA 滤网每 1-2 个月清洗」—— 两条其实都相关。所以 k 不要设成 1，多留几条给大模型自己判断

【在整体流程里的位置】
    agent/tools/kb_tools.search_knowledge → services/kb_service.search
        ① 召回：Chroma 向量检索取 fetch_k 条（config/chroma.yml 的 rerank.fetch_k）
        ② 重排：本文件 rerank()，调用百炼 gte-rerank-v2 打分（model/factory.get_reranker）
        ③ 截断 + 过滤：只留前 k 条，并丢掉分数低于 min_score 的
    → 结果作为 ToolMessage 交给大模型组织回答
阶段：提问时（每次模型调用 search_knowledge 都会执行一次）
相关配置：config/chroma.yml 的 k、rerank 段；config/model.yml 的 rerank 段
"""
from model.factory import get_reranker
from utils.logger_handler import logger


def rerank(query: str, candidates: list[dict], top_n: int, min_score: float | None = None) -> list[dict]:
    """
    给候选资料重新打分排序，只留最相关的 top_n 条。

    参数：
        query：用户问题（和向量检索用的是同一句）
        candidates：向量检索召回的候选，[{"content": 原文, "source": 来源, "distance": 距离, ...}, ...]，按距离从近到远
        top_n：最多留几条（就是 config/chroma.yml 的 k，当前 3）
        min_score：重排分数低于它的丢掉（视为不相关）；None 表示不过滤
    返回：重排后的列表（最多 top_n 条），每条在原来的字段基础上多两个字段：
        rerank_score：重排分数，0 ~ 1，越大越相关
        vector_rank ：它在向量检索里原本排第几（从 1 开始），用来观察重排到底改变了什么
    谁调用：services/kb_service.py 的 search()（rerank.enabled 为 true 时）

    出错时怎么办：重排接口调用失败（网络、限流、key 问题）不让整个检索失败，
    而是退回「向量检索的原始顺序，取前 top_n 条」，并记一条 WARNING 日志。
    为什么：重排只是「锦上添花」，坏了也应该能用向量检索的结果继续回答，而不是让用户看到「系统暂时无法完成」。
    """
    if not candidates:
        return []

    # 记下每条在向量检索里的原始名次（1 = 距离最近），重排后可以对比
    candidates = [dict(c, vector_rank=i) for i, c in enumerate(candidates, start=1)]

    try:
        # DashScopeRerank.rerank(documents, query, top_n)：
        #   documents  候选资料的原文列表（只传文字，不传来源等 metadata）
        #   query      用户问题
        #   top_n      让接口返回前几条。这里传全部候选的数量 —— 费用按「问题 + 全部候选」的长度算，
        #              和返回几条无关；全部拿回来，被 min_score 丢掉的那些也能写进日志，方便调阈值
        #   返回 [{"index": 在 documents 里的位置, "relevance_score": 分数}, ...]，已经按分数从高到低排好
        results = get_reranker().rerank(
            [c["content"] for c in candidates],
            query,
            top_n=len(candidates),
        )
    except Exception as e:
        # 注意：DashScopeRerank 不检查接口返回的状态码，接口报错时这里拿到的往往是一个看不懂的 AttributeError，
        #       真正原因要看日志里的完整堆栈
        logger.warning(f"[重排] 调用失败，退回向量检索顺序：{type(e).__name__}: {e}", exc_info=True)
        return candidates[:top_n]

    ranked = []
    for r in results:
        hit = dict(candidates[r["index"]], rerank_score=round(float(r["relevance_score"]), 4))
        if min_score is not None and hit["rerank_score"] < min_score:
            # DEBUG 只写进日志文件：调 min_score 时去 logs/ 里看被丢掉的分数
            logger.debug(f"[重排] 丢弃低分结果 score={hit['rerank_score']} 原排名={hit['vector_rank']} 来源={hit['source']}")
            continue
        ranked.append(hit)

    kept = ranked[:top_n]
    # 例：「重排 10 → 3｜原排名 [1, 6, 2]」= 召回 10 条，重排后保留 3 条，分别是向量检索里的第 1、6、2 名
    #     出现大于 k 的名次（这里的 6），说明重排把向量检索排得靠后、但其实更相关的资料提了上来
    logger.info(
        f"[重排] 「{query}」{len(candidates)} → {len(kept)} 条"
        f"｜原排名 {[h['vector_rank'] for h in kept]}｜分数 {[h['rerank_score'] for h in kept]}"
    )
    return kept
