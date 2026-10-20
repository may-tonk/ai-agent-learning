"""
报销单工具：claims_get。

对比 v1 的 read_file("data/claims/C002.json")：
  - v1 让模型自己拼文件路径，路径规则写错一个字符就失败；v2 只要报销单号，路径是代码的事
  - v1 返回整份原始 JSON：发票 OCR 全文、支付流水 UUID、审批流、系统元数据……审核时都用不上，
    却占了一大半 token；v2 默认 concise，只返回审核需要的字段，并顺手算好申请总额
  - 真的需要原始数据时（比如核对发票号），可以传 response_format="detailed"
这就是文章里"返回有意义的上下文 + 提供 response_format 让 agent 选择详细程度"的做法。
"""
import json
from typing import Annotated, Literal

from pydantic import Field

import config
from tools.base import ToolArgs
from tools.registry import Tool, ToolError, to_json

# 审核真正需要的字段。其他字段（invoice 原文、payment、_system、approval_chain）在 concise 模式下去掉
_ITEM_FIELDS = ("item_id", "category", "date", "amount", "description", "has_invoice",
                "hotel_city", "check_in", "check_out")


def load_claim(claim_id):
    path = config.CLAIMS_DIR / f"{claim_id}.json"
    if not path.exists():
        existing = sorted(p.stem for p in config.CLAIMS_DIR.glob("*.json"))
        # 报错里直接给出可选的值，模型不用再猜
        raise ToolError(f"找不到报销单 {claim_id}。现有报销单号：{', '.join(existing)}")
    return json.loads(path.read_text(encoding="utf-8"))


def concise_view(claim):
    items = [{k: it[k] for k in _ITEM_FIELDS if k in it} for it in claim["items"]]
    return {
        "claim_id": claim["claim_id"],
        "employee": {"name": claim["employee"]["name"], "department": claim["employee"]["department"]},
        "submit_date": claim["submit_date"],
        "trip": claim["trip"],     # None 表示本地费用，不是出差
        "item_count": len(items),
        "requested_total": round(sum(it["amount"] for it in claim["items"]), 2),
        "items": items,
    }


class ClaimsGetArgs(ToolArgs):
    claim_id: Annotated[str, Field(pattern=r"^C\d{3}$", description="报销单号，格式为 C 加 3 位数字，例如 C002")]
    response_format: Annotated[Literal["concise", "detailed"], Field(
        description="concise（推荐）：只返回审核需要的字段；detailed：返回完整原始记录，含发票 OCR 全文和系统字段，"
                    "只有需要核对发票号、支付流水时才用")]


def claims_get(args: ClaimsGetArgs) -> str:
    claim = load_claim(args.claim_id)
    data = concise_view(claim) if args.response_format == "concise" else claim
    return to_json(data)


TOOLS = [
    Tool("claims_get",
         "按报销单号读取一张报销单：员工、提交日期、出差行程（trip 为 null 表示本地费用）、每一笔费用的类别/日期/金额/说明/是否有发票，"
         "以及申请总额 requested_total。审核开始时先调用它。",
         ClaimsGetArgs, claims_get),
]
