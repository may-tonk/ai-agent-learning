"""
审核结果的数据结构：agent 最后交出来的"审核单"长什么样。

为什么要固定结构？因为审核结论不是给人随便读的一段话，而是要交给后面的程序：
写进财务系统、触发打款、转给总监审批。程序只能读固定格式的数据，所以必须是结构化输出。

做法（Day 4 学过）：用 Pydantic 定义结构 →
  1. 自动生成 JSON Schema，作为 review_submit 工具的参数说明发给模型
  2. 模型提交后，用同一个类做校验；校验不通过就把错误原因返回给模型，让它改了再交

这里除了字段类型，还加了"业务一致性"校验（金额加总、状态和金额对得上、结论和状态对得上）。
这类校验 JSON Schema 表达不了，只能写在代码里，也是真实项目里最能拦住错误的一层。
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TOLERANCE = 0.01   # 金额比较允许的误差（浮点数加减会有 0.000001 级别的误差）

ItemStatus = Literal["approved", "adjusted", "rejected", "pending"]
Decision = Literal["approve", "partial", "reject", "needs_review"]


class ItemFinding(BaseModel):
    """一笔费用的审核结果。"""
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(description="费用编号，例如 C002-02")
    status: ItemStatus = Field(description="approved 全额通过；adjusted 核减后通过；rejected 不予报销；pending 待人工复核")
    requested_amount: float = Field(description="这笔费用的申请金额（元）")
    approved_amount: float = Field(description="这笔费用的核定金额（元）。rejected 和 pending 必须填 0")
    policy_refs: list[str] = Field(description="依据的制度条款编号，例如 [\"P2.1\", \"P2.2\"]；全额通过且无特别依据时可以为空列表")
    reason: str = Field(description="一句话说明理由，核减时写出计算过程，例如 '3 晚 × 600 = 1800，超出 540 元自理'")

    @model_validator(mode="after")
    def check_amounts(self):
        if self.approved_amount < -TOLERANCE:
            raise ValueError(f"{self.item_id}: approved_amount 不能是负数")
        if self.approved_amount > self.requested_amount + TOLERANCE:
            raise ValueError(f"{self.item_id}: 核定金额 {self.approved_amount} 不能大于申请金额 {self.requested_amount}")
        if self.status in ("rejected", "pending") and abs(self.approved_amount) > TOLERANCE:
            raise ValueError(f"{self.item_id}: 状态是 {self.status} 时 approved_amount 必须是 0")
        if self.status == "approved" and abs(self.approved_amount - self.requested_amount) > TOLERANCE:
            raise ValueError(f"{self.item_id}: 状态是 approved 时核定金额应等于申请金额；如果有核减，状态应为 adjusted")
        return self


class ReviewResult(BaseModel):
    """一张报销单的完整审核结论。"""
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(description="报销单号，例如 C002")
    decision: Decision = Field(description="整张报销单的结论，按制度 P6.2 的顺序确定")
    requested_total: float = Field(description="所有费用申请金额之和（元）")
    approved_total: float = Field(description="核定总额 = 所有 approved/adjusted 费用的 approved_amount 之和（元），不含 pending")
    items: list[ItemFinding] = Field(description="每一笔费用的审核结果，报销单里的每一笔都要有")
    summary: str = Field(description="给员工看的一两句话总结")

    @model_validator(mode="after")
    def check_consistency(self):
        errors = []
        item_req = sum(i.requested_amount for i in self.items)
        item_ok = sum(i.approved_amount for i in self.items)
        if abs(item_req - self.requested_total) > TOLERANCE:
            errors.append(f"requested_total={self.requested_total}，但各笔 requested_amount 之和是 {item_req:.2f}")
        if abs(item_ok - self.approved_total) > TOLERANCE:
            errors.append(f"approved_total={self.approved_total}，但各笔 approved_amount 之和是 {item_ok:.2f}")
        # 结论必须和各笔状态一致（制度 P6.2）。P1.4 的"超过 5000"也在这里检查。
        statuses = {i.status for i in self.items}
        if "pending" in statuses or self.approved_total > 5000 + TOLERANCE:
            expected = "needs_review"
        elif abs(self.approved_total) <= TOLERANCE:
            expected = "reject"
        elif statuses & {"adjusted", "rejected"}:
            expected = "partial"
        else:
            expected = "approve"
        if self.decision != expected:
            errors.append(f"按 P6.2，当前各笔状态和核定总额对应的结论应是 {expected}，而不是 {self.decision}")
        if errors:
            # 报错写成"哪里不对 + 应该怎么改"，模型拿到后能直接修正（第一段讲的原则 ③）
            raise ValueError("；".join(errors) + "。请用 calc_evaluate 重新核对金额后再提交。")
        return self
