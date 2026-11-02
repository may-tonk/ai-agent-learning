"""
工单分析：让模型输出"结构化结果"，而不是一段自由文字。

场景：客服系统每收到一条客户消息，先让模型判断意图、情绪、紧急程度，
     再由代码根据这些字段决定：直接让 agent 处理，还是转人工、优先处理。
     代码要读这些字段，所以模型的输出必须是格式固定、能被程序可靠解析的 JSON。

三种拿到结构化输出的方法（可靠程度从低到高）：
  1. 只在提示词里说"请输出 JSON"：模型经常加 ```json 代码块、加解释文字，解析会失败
  2. JSON 模式 response_format={"type": "json_object"}：保证输出是合法 JSON，
     但不保证字段对不对（可能少字段、枚举值写错）→ 所以还要用 Pydantic 校验
  3. 结构化输出 response_format={"type": "json_schema", "json_schema": {..., "strict": True}}：
     服务端按 schema 约束生成，字段一定对。OpenAI 官方模型支持，
     OpenAI SDK 还提供 client.chat.completions.parse(response_format=某个Pydantic类) 直接返回对象。
     DeepSeek 文档目前只写了 json_object，所以本项目用第 2 种 + Pydantic 校验 + 失败重试。

DeepSeek JSON 模式的官方要求（https://api-docs.deepseek.com/guides/json_mode）：
  - 提示词里必须出现 "json" 这个词
  - 最好给出期望的 JSON 示例
  - max_tokens 要够大，否则 JSON 会被截断
  - 偶尔会返回空内容 → 代码要能处理（这里当作一次失败，进入重试）
"""
import json
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from common import EXTRA_BODY, MODEL
from tools import OrderId, format_errors

MAX_ATTEMPTS = 3      # 最多问几次（第 1 次 + 最多 2 次重试）


# ============================================================
# 1. 期望的输出结构：一个 Pydantic 模型
# ============================================================
class TicketAnalysis(BaseModel):
    intent: Literal["查询订单", "查询物流", "申请退款", "投诉", "咨询", "表扬", "其他"] = Field(
        description="客户的主要意图")
    order_id: Optional[OrderId] = Field(default=None, description="消息里提到的订单号，没有就是 null")
    sentiment: Literal["positive", "neutral", "negative"] = Field(description="客户情绪")
    urgency: int = Field(ge=1, le=5, description="紧急程度，1 最低 5 最高")
    needs_human: bool = Field(description="金额较大、情绪激烈或超出 agent 能力时为 true")
    summary: str = Field(max_length=40, description="一句话概括，不超过 40 个字")


class AnalysisResult(BaseModel):
    """analyze_ticket 的返回值：分析结果 + 过程信息（第几次成功、用了多少 token）"""
    analysis: TicketAnalysis
    attempts: int
    prompt_tokens: int
    completion_tokens: int


class TicketParseError(Exception):
    """重试 MAX_ATTEMPTS 次后仍然得不到合格的 JSON"""


# ============================================================
# 2. 提示词：包含 "json" 这个词 + 完整 schema + 一个示例
# ============================================================
EXAMPLE = {"intent": "查询物流", "order_id": "ORD100099", "sentiment": "neutral",
           "urgency": 2, "needs_human": False, "summary": "客户询问订单的物流进度"}

SYSTEM_PROMPT = f"""你是电商客服系统的工单分析器。分析客户消息，只输出一个 json 对象，不要输出任何其他文字。
json 必须符合下面的 JSON Schema：
{json.dumps(TicketAnalysis.model_json_schema(), ensure_ascii=False)}

示例输出：
{json.dumps(EXAMPLE, ensure_ascii=False)}"""


def build_messages(text):
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text}]


def check(content):
    """校验模型的输出。返回 (分析结果, None) 或 (None, 给模型的纠错提示)。"""
    if not content or not content.strip():
        return None, "你上次返回了空内容。请只输出符合要求的 json 对象。"
    try:
        return TicketAnalysis.model_validate_json(content), None
    except ValidationError as e:
        return None, f"你上次输出的 json 没有通过校验：{format_errors(e)}。请修正后只输出 json 对象。"


def _request_kwargs(messages):
    return dict(model=MODEL, messages=messages,
                response_format={"type": "json_object"},   # 开启 JSON 模式
                max_tokens=300, temperature=0, extra_body=EXTRA_BODY)


# ============================================================
# 3. 同步版本：问 → 校验 → 不合格就把错误告诉模型，让它改
# ============================================================
def analyze_ticket(client, text, verbose=False):
    messages = build_messages(text)
    p_tokens = c_tokens = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        resp = client.chat.completions.create(**_request_kwargs(messages))
        p_tokens += resp.usage.prompt_tokens
        c_tokens += resp.usage.completion_tokens
        content = resp.choices[0].message.content
        analysis, feedback = check(content)
        if verbose:
            print(f"  第 {attempt} 次原始输出：{content}")
            print(f"  校验：{'通过' if analysis else feedback}")
        if analysis:
            return AnalysisResult(analysis=analysis, attempts=attempt,
                                  prompt_tokens=p_tokens, completion_tokens=c_tokens)
        # 重试的关键：把模型错误的输出和错误原因都放回对话，它才知道该改哪里
        messages += [{"role": "assistant", "content": content or ""},
                     {"role": "user", "content": feedback}]
    raise TicketParseError(f"重试 {MAX_ATTEMPTS} 次后仍然失败：{feedback}")


# ============================================================
# 4. 异步版本：逻辑和上面一模一样，区别只有两处：
#    def → async def；client.chat.completions.create(...) 前面加 await
#    （client 必须是 AsyncOpenAI）。04 和 server.py 用这个版本。
# ============================================================
async def analyze_ticket_async(client, text):
    messages = build_messages(text)
    p_tokens = c_tokens = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        resp = await client.chat.completions.create(**_request_kwargs(messages))
        p_tokens += resp.usage.prompt_tokens
        c_tokens += resp.usage.completion_tokens
        content = resp.choices[0].message.content
        analysis, feedback = check(content)
        if analysis:
            return AnalysisResult(analysis=analysis, attempts=attempt,
                                  prompt_tokens=p_tokens, completion_tokens=c_tokens)
        messages += [{"role": "assistant", "content": content or ""},
                     {"role": "user", "content": feedback}]
    raise TicketParseError(f"重试 {MAX_ATTEMPTS} 次后仍然失败：{feedback}")
