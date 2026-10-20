"""
制度查询工具：policy_search。

对比 v1 的 read_file("data/policy.md")：v1 一次把整份制度读进上下文，而且之后每一步都要背着它。
今天的制度只有几十行，看不出差别；真实公司的报销制度、合同、知识库动辄几万字，整份塞进去既贵又会让模型"看漏"（上下文腐烂）。
v2 按关键词检索，只返回相关的章节，并带上条款编号，模型在结论里可以直接引用 P2.1 这样的依据。

这里用最简单的关键词打分实现检索。真实项目会换成全文检索（Elasticsearch）或向量检索（第 3 周 Day 15 学），
但工具的"接口"（输入关键词、返回带编号的相关条款）不用变，这正是把工具接口设计好的价值。
"""
import re
from functools import lru_cache
from typing import Annotated, Optional

from pydantic import Field

import config
from tools.base import ToolArgs
from tools.registry import Tool, ToolError, to_json

_SPLIT = re.compile(r"[\s,，、;；/]+")
_SECTION_ID = re.compile(r"^P\d+(\.\d+)?$", re.IGNORECASE)


@lru_cache(maxsize=1)
def load_sections():
    """把 policy.md 按 '## ' 二级标题切成章节：[{"id": "P2", "title": "住宿", "text": "..."}]"""
    text = config.POLICY_FILE.read_text(encoding="utf-8")
    sections = []
    for block in text.split("\n## ")[1:]:
        header, _, body = block.partition("\n")
        sec_id, _, title = header.strip().partition(" ")
        sections.append({"id": sec_id, "title": title, "text": body.strip()})
    return sections


def _score(section, terms):
    return sum(section["text"].count(t) + 3 * section["title"].count(t) for t in terms)


def search(query, max_results=2):
    sections = load_sections()
    terms = [t for t in _SPLIT.split(query.strip()) if t]
    # 直接按条款编号查：P2 或 P2.1 → 返回所在章节
    ids = [t.upper().split(".")[0] for t in terms if _SECTION_ID.match(t)]
    if ids:
        return [s for s in sections if s["id"] in ids]
    scored = [(s, _score(s, terms)) for s in sections]
    if not any(score for _, score in scored):
        # 整词没命中（比如模型写了 "一线城市住宿上限" 这种长词），退一步按两个字一组匹配
        bigrams = [t[i:i + 2] for t in terms for i in range(len(t) - 1)]
        scored = [(s, _score(s, bigrams)) for s in sections]
    scored = [(s, sc) for s, sc in scored if sc > 0]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in scored[:max_results]]


class PolicySearchArgs(ToolArgs):
    query: Annotated[str, Field(description="用空格分隔的关键词，例如 '住宿 标准'、'业务招待 人均'、'出租车 原因'；"
                                            "也可以直接写条款编号，例如 'P3' 或 'P2.1'")]
    max_results: Annotated[Optional[int], Field(description="最多返回几个章节，默认 2；不确定时传 null")]


def policy_search(args: PolicySearchArgs) -> str:
    hits = search(args.query, args.max_results or 2)
    if not hits:
        catalog = "；".join(f"{s['id']} {s['title']}" for s in load_sections())
        raise ToolError(f"没有找到和 '{args.query}' 相关的条款。制度目录：{catalog}。"
                        f"可以换更短的关键词，或者直接用章节编号查询，例如 'P2'")
    return to_json([{"section": f"{s['id']} {s['title']}", "text": s["text"]} for s in hits])


TOOLS = [
    Tool("policy_search",
         "在公司报销制度中检索相关条款，返回章节编号、标题和条款全文。判断任何一笔费用之前，都要先查到对应条款，"
         "结论里引用条款编号（如 P2.1）。制度共 6 章：P1 通用规则（发票、60 天时限、5000 元复核）、P2 住宿、P3 餐饮（含业务招待、内部聚餐）、"
         "P4 交通、P5 不予报销的费用、P6 审核结论的确定方式。",
         PolicySearchArgs, policy_search),
]
