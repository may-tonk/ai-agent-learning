"""
测试用的"假模型"：按剧本依次返回预先写好的响应，不连网、不花钱。

真实项目里，agent 循环的逻辑（并行调用、校验失败重试、步数上限）必须能脱离真实模型测试：
真实模型每次回答都可能不一样，没法写成稳定的测试。所以测试分两层：
  - 单元测试 + 假模型：验证"程序逻辑"对不对（本目录）
  - 评测（run_eval.py）+ 真实模型：验证"整体效果"好不好
"""
import json

from openai.types.chat import ChatCompletion


def make_response(content=None, tool_calls=(), finish_reason=None, prompt_tokens=100, completion_tokens=20):
    """构造一个和 OpenAI SDK 返回值结构完全相同的 ChatCompletion 对象。
    tool_calls: [(call_id, 工具名, 参数 dict), ...]"""
    calls = [{"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
             for cid, name, args in tool_calls]
    return ChatCompletion.model_validate({
        "id": "fake", "object": "chat.completion", "created": 0, "model": "fake-model",
        "choices": [{"index": 0, "finish_reason": finish_reason or ("tool_calls" if calls else "stop"),
                     "message": {"role": "assistant", "content": content, "tool_calls": calls or None}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                  "total_tokens": prompt_tokens + completion_tokens},
    })


class FakeClient:
    """用法：client = FakeClient([响应1, 响应2, ...])，之后 client.chat.completions.create(...) 依次返回它们。
    每次收到的请求记录在 client.requests 里，测试可以检查发出去的内容对不对。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        # 深拷贝一份 messages：agent 循环之后还会往同一个列表里追加，不拷贝的话记录会跟着变
        self.requests.append(json.loads(json.dumps({k: v for k, v in kwargs.items() if k != "extra_body"}, default=str)))
        if not self._responses:
            raise AssertionError("假模型的剧本已经用完，agent 多调用了一次模型")
        return self._responses.pop(0)
