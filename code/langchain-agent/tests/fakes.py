"""
假模型：按剧本依次返回预先写好的 AIMessage

为什么需要：真实模型每次输出不一样、要花钱、要联网。测试「工具权限、State 更新、审批中断」
这些程序逻辑时，我们只关心「如果模型这样请求，程序会怎么处理」，所以用假模型把模型的输出固定下来。
lessons/03 也用它来演示工具机制，不需要 API key。
"""
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedChatModel(BaseChatModel):
    """
    继承 BaseChatModel，只实现 _generate：每被调用一次，返回剧本里的下一条消息。
    received 记录每次收到的消息列表，测试里可以检查「模型到底看到了什么」。
    """

    replies: list[AIMessage]
    received: list = []
    tools_seen: list = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.received.append(list(messages))
        if not self.replies:
            raise RuntimeError("剧本里的回复已经用完了")
        reply = self.replies.pop(0)
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def bind_tools(self, tools, **kwargs):
        # agent 每次调用模型前都会 bind_tools；记录下这次模型能看到哪些工具，然后返回自己
        self.tools_seen.append([_tool_name(t) for t in tools])
        return self


def _tool_name(t) -> str:
    """
    工具的名字。bind_tools 收到的东西有三种：@tool 工具对象（有 .name）、字典（{"name": ...}）、
    Pydantic 类 —— 【阶段 5】with_structured_output(ServiceSummary) 就是把这个类当成工具传进来的，名字取类名
    """
    if isinstance(t, type):
        return t.__name__
    return getattr(t, "name", None) or t.get("name")


def scripted(*replies: AIMessage) -> ScriptedChatModel:
    return ScriptedChatModel(replies=list(replies), received=[], tools_seen=[])


def call(name: str, args: dict, call_id: str = "call_1", text: str = "") -> AIMessage:
    """模型「请求调用工具」的那种回复"""
    return AIMessage(
        content=text,
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
        usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
    )


def answer(text: str) -> AIMessage:
    """模型「直接回答」的那种回复"""
    return AIMessage(
        content=text,
        usage_metadata={"input_tokens": 150, "output_tokens": 40, "total_tokens": 190},
    )
