"""
工具注册表：把"一个工具"需要的东西打包在一起，并负责把模型的调用请求安全地执行掉。

一个工具 = 名字 + 说明 + 参数模型（Pydantic）+ 真正干活的函数。
一组工具 = Toolset：v1（D3 原始版）和 v2（按原则重构版）各是一个 Toolset，agent 循环不关心用的是哪一组。

这个文件还负责"协议翻译"：同一个工具，
  - 发给 OpenAI 协议时包成 {"type": "function", "function": {"name", "description", "parameters"}}
  - 发给 Anthropic 协议时写成 {"name", "description", "input_schema"}
工具本身只写一次，翻译成哪种格式由这里决定。LangChain 的 bind_tools 做的也是这件事。
"""
import json
from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel, ValidationError

from schemas.strict import to_strict_schema


class ToolError(Exception):
    """工具执行中"预料之内"的失败（找不到报销单、表达式写错等）。
    message 是写给模型看的：要说清楚哪里错了、下一步该怎么做。"""


@dataclass
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    func: Callable[[BaseModel], str]


@dataclass
class Toolset:
    name: str
    tools: list[Tool]
    strict: bool = False              # 是否开启严格模式（开了就所有工具都开，DeepSeek 要求一致）
    max_chars: int = 4000             # 工具结果长度上限
    announce_truncation: bool = True  # 截断时是否告诉模型（v1 照搬 Day 7：不告诉）
    _by_name: dict = field(init=False, repr=False)

    def __post_init__(self):
        self._by_name = {t.name: t for t in self.tools}

    # ---------- 协议翻译：同一组工具，两种格式 ----------
    def _schema(self, tool):
        schema = tool.args_model.model_json_schema()
        return to_strict_schema(schema) if self.strict else schema

    def openai_tools(self):
        out = []
        for t in self.tools:
            fn = {"name": t.name, "description": t.description, "parameters": self._schema(t)}
            if self.strict:
                fn["strict"] = True
            out.append({"type": "function", "function": fn})
        return out

    def anthropic_tools(self):
        # Anthropic 没有外面那层 {"type": "function"} 包装，参数说明的字段名叫 input_schema
        return [{"name": t.name, "description": t.description, "input_schema": self._schema(t)} for t in self.tools]

    # ---------- 执行一次工具调用 ----------
    def execute(self, name, raw_args):
        """执行模型请求的一次工具调用，返回 (给模型看的文本, 是否出错)。

        raw_args 可以是 JSON 字符串（OpenAI 协议：arguments 是字符串）
        也可以是 dict（Anthropic 协议：input 已经是对象）。
        任何错误都变成文字返回给模型，程序本身不会崩。
        """
        tool = self._by_name.get(name)
        if tool is None:
            return f"错误：没有名为 {name} 的工具。可用的工具有：{', '.join(self._by_name)}", True
        try:
            if isinstance(raw_args, str):
                args = tool.args_model.model_validate_json(raw_args or "{}")
            else:
                args = tool.args_model.model_validate(raw_args or {})
        except ValidationError as e:
            return f"参数不符合要求：{format_validation_error(e)}。请按工具说明修正参数后重新调用。", True
        try:
            text = tool.func(args)
            is_error = False
        except ToolError as e:
            text, is_error = str(e), True
        except Exception as e:  # 预料之外的 bug：也不能让 agent 崩掉，但要标记出来方便排查
            text, is_error = f"工具内部错误：{type(e).__name__}: {e}", True
        return self._limit(text), is_error

    def _limit(self, text):
        if len(text) <= self.max_chars:
            return text
        if self.announce_truncation:
            return (text[: self.max_chars]
                    + f"\n...[结果过长已截断：共 {len(text)} 字符，只显示前 {self.max_chars} 字符。请缩小查询范围]")
        return text[: self.max_chars]       # 静默截断：模型不知道后面还有内容


def format_validation_error(e: ValidationError):
    """把 Pydantic 的报错压缩成一行，例如：claim_id: String should match pattern '^C\\d{3}$'"""
    parts = []
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"]) or "(整体)"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


def to_json(data):
    """工具结果统一用紧凑 JSON（中文不转义），比带缩进的 JSON 省 token。"""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
