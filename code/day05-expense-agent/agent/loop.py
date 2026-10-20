"""
agent 循环（OpenAI 协议）：整个 agent 的"心脏"，结构和 Day 7 的 agent_deepseek.py 一样，补上了工程上要有的几样东西：

  - 支持并行工具调用：模型一次可能要求调用好几个工具，每一个都要执行、都要回传结果
  - 最终结论走 review_submit：校验通过才算完成，没通过就把错误还给模型重来
  - 模型"光说不做"（直接回复文字、没提交）时提醒它一次
  - 统计每一步的 token、工具调用次数、工具错误次数，评测脚本要用这些数字来比较 v1 和 v2
  - 完整记录每一轮发了什么、收到什么（transcript），出问题时可以回放排查

循环本身不打印任何东西，而是通过 on_event 回调把发生的事情交给调用方，
由脚本决定是打印到终端、写日志还是推给前端（Day 7 的 SSE 服务就是这么接的）。
"""
import json
from dataclasses import dataclass, field

import config
from schemas.review import ReviewResult
from tools.submit import SUBMIT_TOOL_NAME


@dataclass
class AgentRun:
    """一次 agent 运行的结果和统计数据。"""
    result: ReviewResult | None = None
    stop_reason: str = ""            # submitted / max_steps / no_submit
    steps: int = 0                   # 调用了几次模型
    tool_calls: int = 0              # 一共执行了几次工具
    tool_errors: int = 0             # 其中出错的次数
    parallel_batches: int = 0        # 有几步是一次性要求了多个工具（并行调用）
    prompt_tokens: int = 0
    completion_tokens: int = 0
    messages: list = field(default_factory=list)    # 完整对话记录

    def stats(self):
        return {k: getattr(self, k) for k in ("stop_reason", "steps", "tool_calls", "tool_errors",
                                              "parallel_batches", "prompt_tokens", "completion_tokens")}


def run_agent(client, model, system_prompt, task, toolset, *, max_steps=config.MAX_STEPS,
              extra_body=None, on_event=None):
    """运行 agent 直到提交结论或达到步数上限。client 是 OpenAI SDK 的客户端（或测试用的假客户端）。"""
    emit = on_event or (lambda kind, data: None)
    run = AgentRun()
    messages = [
        {"role": "system", "content": system_prompt},   # OpenAI 协议：system 是 messages 里的第一条
        {"role": "user", "content": task},
    ]
    run.messages = messages
    tools = toolset.openai_tools()
    nudged = False

    for step in range(1, max_steps + 1):
        request = {"model": model, "messages": messages, "tools": tools, "temperature": config.TEMPERATURE}
        emit("request", {"step": step, "request": request})
        resp = client.chat.completions.create(**request, extra_body=extra_body or None)
        run.steps = step
        usage = resp.usage
        if usage:
            run.prompt_tokens += usage.prompt_tokens
            run.completion_tokens += usage.completion_tokens
        choice = resp.choices[0]
        msg = choice.message
        emit("response", {"step": step, "response": resp, "finish_reason": choice.finish_reason,
                          "prompt_tokens": usage.prompt_tokens if usage else None,
                          "completion_tokens": usage.completion_tokens if usage else None})

        # 模型的回复（文字 + 它想调用的工具）原样放回历史。转成 dict，方便之后写日志
        messages.append(_assistant_to_dict(msg))
        if msg.content:
            emit("thought", {"step": step, "text": msg.content})

        # finish_reason 不是 tool_calls：模型认为说完了。但我们要的是 review_submit，不是一段文字
        if choice.finish_reason != "tool_calls" or not msg.tool_calls:
            if nudged:
                run.stop_reason = "no_submit"
                return run
            nudged = True
            messages.append({"role": "user", "content": f"请调用 {SUBMIT_TOOL_NAME} 工具提交审核结论，不要只用文字回复。"})
            emit("nudge", {"step": step})
            continue

        if len(msg.tool_calls) > 1:
            run.parallel_batches += 1
        # 并行调用：一条 assistant 消息里有多个 tool_calls。
        # OpenAI 协议要求：每一个 tool_call 都必须有一条 role=tool 的结果消息，用 tool_call_id 对应，缺一条下次请求就会报错。
        # 这里按顺序执行；工具都是快速的本地操作，不需要真的多线程。工具慢（查数据库、调接口）时可以用 Day 4 学的并发。
        for call in msg.tool_calls:
            name, raw_args = call.function.name, call.function.arguments   # arguments 是 JSON 字符串
            output, is_error = toolset.execute(name, raw_args)
            run.tool_calls += 1
            run.tool_errors += is_error
            emit("tool", {"step": step, "name": name, "args": raw_args, "output": output, "is_error": is_error})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": output})
            if name == SUBMIT_TOOL_NAME and not is_error:
                run.result = ReviewResult.model_validate_json(raw_args)

        if run.result is not None:
            run.stop_reason = "submitted"
            return run

    run.stop_reason = "max_steps"
    return run


def _assistant_to_dict(msg):
    """把 SDK 返回的消息对象转成普通 dict（发回给服务端和写日志都用这个格式）。"""
    d = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        d["tool_calls"] = [{"id": c.id, "type": "function",
                            "function": {"name": c.function.name, "arguments": c.function.arguments}}
                           for c in msg.tool_calls]
    return d


def dump_transcript(run: AgentRun):
    """把一次运行整理成可以写进 JSON 文件的数据。"""
    return {"stats": run.stats(), "result": run.result.model_dump() if run.result else None, "messages": run.messages}


def to_jsonable(obj):
    """SDK 的响应对象 → 普通 dict，用于 --show-json 打印原始 JSON。"""
    return obj.model_dump(exclude_none=True) if hasattr(obj, "model_dump") else obj


def pretty(obj):
    return json.dumps(to_jsonable(obj), ensure_ascii=False, indent=2)
