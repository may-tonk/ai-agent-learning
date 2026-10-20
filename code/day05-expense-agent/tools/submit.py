"""
提交工具：review_submit。参数就是 schemas/review.py 里的 ReviewResult。

这是真实项目里很常用的"最终答案工具"模式：
  - 不让模型用一段文字回答，而是要求它调用 review_submit，把结论填进固定结构
  - 参数校验（含金额加总、结论一致性）不通过 → 错误原因作为工具结果返回，模型改了再交
  - 校验通过 → agent 循环结束，程序拿到的是一个 ReviewResult 对象，可以直接写库

OpenAI 官方接口还有另一种做法：最后一步用 response_format={"type": "json_schema", ...}（structured outputs）。
DeepSeek 的 response_format 只支持 json_object，不支持 json_schema，所以这里用"工具 + strict"实现同样的效果。
两种做法的本质一样：用 JSON Schema 约束模型的输出。
"""
from schemas.review import ReviewResult
from tools.registry import Tool

SUBMIT_TOOL_NAME = "review_submit"


def review_submit(args: ReviewResult) -> str:
    # 能走到这里说明参数校验已经通过；真正的"保存结果"由 agent 循环处理
    return f"审核结论已提交：{args.claim_id} {args.decision}，核定总额 {args.approved_total}"


TOOL = Tool(SUBMIT_TOOL_NAME,
            "提交整张报销单的最终审核结论。所有费用都判断完、金额都用工具算好之后调用，每张报销单只提交一次。"
            "如果返回校验错误，按错误提示修正后重新提交。",
            ReviewResult, review_submit)
