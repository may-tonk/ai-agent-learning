"""
会话小结：一次对话结束后，生成一份结构化的服务记录

【Models 模块：结构化输出】
model.with_structured_output(ServiceSummary)：把 Pydantic 类交给模型，
模型返回的不再是一段文字，而是一个已经校验过的 ServiceSummary 对象。
这里不需要工具、也不需要循环，所以直接用模型，不用 agent。

【在整体流程里的位置】不在 agent 循环里，是对话之外的一次独立模型调用：
    命令行：main.py 输入 /summary → show_summary → 本文件 summarize_session（同步）→ DeepSeek
    网页  ：「生成小结」按钮 → POST /api/threads/{id}/summary → 本文件 asummarize_session（异步，阶段 5）→ DeepSeek
真实客服系统里，这一步通常在对话结束后由后台自动执行，结果存进数据库做统计、质检。

【阶段 5 改了什么】
    ① 加了异步版 asummarize_session：网页后端是异步的，用同步版会在等 DeepSeek 的几秒里卡住所有请求
    ② 出错处理：对话为空 → RuleViolationError；模型没按格式返回 → SummaryError（都在 services/errors.py），
       接口转成 HTTP 400 / 502，页面显示提示
    ③ 对话稿更精简：知识库原文不发给模型（小结用不上，很占 token）；摘要中间件压缩过的部分标出来
    ④ model 参数：可以传入模型（测试传假模型）；不传就和以前一样用 config/model.yml 的 summary 段
"""
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import ValidationError

from agent.schemas import ServiceSummary
from model.factory import build_chat_model
from services.errors import RuleViolationError, SummaryError
from utils.logger_handler import logger
from utils.prompt_loader import load_prompt

# 【阶段 5】工具结果最多保留多少字：订单详情、工单号都在前面，300 字足够；再长就是浪费 token
TOOL_RESULT_LIMIT = 300
# 【阶段 5】这些工具的结果不发原文：知识库检索返回的是几段说明书原文（动辄上千字），
#   小结只需要知道「客服查过资料」，答案本身在客服的回答里已经有了
OMIT_RESULT_TOOLS = {"search_knowledge"}


def _render_transcript(messages: list[BaseMessage]) -> str:
    """
    把消息列表转成「谁说了什么」的纯文本，只保留和小结有关的内容
    为什么不直接把消息列表发给模型：原始消息里有 tool_call_id、JSON 等噪音，
    转成对话稿更省 token，模型也更容易看懂。
    """
    lines = []
    for m in messages:
        if isinstance(m, HumanMessage):
            # 【阶段 5】对话很长时，SummarizationMiddleware 会把旧消息压缩成一条 HumanMessage，
            #   并在 additional_kwargs 里做标记 lc_source="summarization"（langchain 源码 summarization.py 的 _build_new_messages）。
            #   它不是用户说的话，按「用户：」写进对话稿会误导模型，所以单独标出来
            if m.additional_kwargs.get("lc_source") == "summarization":
                lines.append(f"（较早的对话已压缩成摘要）{m.text}")
            else:
                lines.append(f"用户：{m.text}")
        elif isinstance(m, AIMessage):
            if m.tool_calls:
                calls = "，".join(f"{c['name']}({c['args']})" for c in m.tool_calls)
                lines.append(f"客服调用工具：{calls}")
            if m.text:
                lines.append(f"客服：{m.text}")
        elif isinstance(m, ToolMessage):
            if m.name in OMIT_RESULT_TOOLS:
                lines.append(f"工具结果（{m.name}）：检索到知识库资料（原文略）")
            else:
                lines.append(f"工具结果（{m.name}）：{str(m.content)[:TOOL_RESULT_LIMIT]}")
    return "\n".join(lines)


def _build_prompt(messages: list[BaseMessage]) -> list[BaseMessage]:
    """
    【阶段 5】同步版和异步版共用：拼出发给模型的两条消息（质检员提示词 + 对话稿）。
    异常：对话里还没有用户说的话 → RuleViolationError（没东西可总结，不用白花一次模型调用）
    """
    if not any(isinstance(m, HumanMessage) for m in messages):
        raise RuleViolationError("这段对话还没有内容，先聊几句再生成小结")
    return [SystemMessage(load_prompt("session_summary")), HumanMessage(_render_transcript(messages))]


def _structured(model: BaseChatModel | None):
    """
    model：None = 用 config/model.yml 的 summary 段（temperature 0，小结要稳定）；测试时传假模型
    with_structured_output(Pydantic 类)：
        DeepSeek 默认用 function_calling 方式实现 —— 把 ServiceSummary 当成一个「工具」让模型调用，
        再把模型填的参数解析、校验成 ServiceSummary 对象。所以模型必须支持工具调用。
        Field 的 description 会发给模型，写得越清楚，模型填得越准
    """
    return (model or build_chat_model("summary")).with_structured_output(ServiceSummary)


def _check(result) -> ServiceSummary:
    """【阶段 5】模型没调用 ServiceSummary 这个「工具」（直接回了一段文字）时，结构化输出返回 None，这里统一当成失败"""
    if result is None:
        raise SummaryError("模型没有按格式返回小结，请重试")
    return result


def summarize_session(messages: list[BaseMessage], model: BaseChatModel | None = None) -> ServiceSummary:
    """
    同步版（命令行 main.py 的 /summary 用）。
    messages：checkpointer 里这段对话的全部消息（session.state()["messages"]）
    返回：ServiceSummary 对象（字段见 agent/schemas.py），可以 .model_dump() 转成字典存库
    """
    prompt = _build_prompt(messages)
    try:
        return _check(_structured(model).invoke(prompt))
    except (ValidationError, OutputParserException) as e:
        logger.warning(f"[小结] 模型返回的小结不符合格式：{e}")
        raise SummaryError("模型返回的小结格式不对，请重试") from e


async def asummarize_session(messages: list[BaseMessage], model: BaseChatModel | None = None) -> ServiceSummary:
    """
    【阶段 5】异步版（网页后端用），逻辑和上面完全一样，只是 invoke → await ainvoke。
    异常：
        RuleViolationError：对话为空
        SummaryError：模型返回的格式不对（字段缺失、category 不在可选值里 → Pydantic 校验失败；或者根本没按格式返回）
        ModelError：DeepSeek 连不上、超时、限流 —— 不在这里处理，交给接口按类型转成 429 / 504 / 502
    真实项目里同一个功能常常同时有同步、异步两个版本（LangChain 自己就是 invoke / ainvoke 成对出现），
    共用的部分（拼提示词、检查结果）抽成函数，两个版本只差「怎么调用模型」这一行。
    """
    prompt = _build_prompt(messages)
    try:
        return _check(await _structured(model).ainvoke(prompt))
    except (ValidationError, OutputParserException) as e:
        logger.warning(f"[小结] 模型返回的小结不符合格式：{e}")
        raise SummaryError("模型返回的小结格式不对，请重试") from e
