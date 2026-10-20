"""
入口 3：两家 tool use 协议对比。把同一个任务、同样的两个工具，分别用 OpenAI 协议和 Anthropic 协议发一遍，
打印双方真实的请求和响应 JSON，并把工具结果按各自的规矩回传，完成一次完整的往返。

两边连的都是 DeepSeek（它同时提供两种兼容接口），所以只需要你现有的 DEEPSEEK_API_KEY。
注意：DeepSeek 的 Anthropic 兼容接口会忽略 tool_result 里的 is_error 字段，也不能关闭并行调用；
真正的 Claude 接口这两项都支持。协议的"结构"两者完全一致，这正是我们要对比的东西。

用法：
    python code/day05-expense-agent/compare_protocols.py
"""
import json
from datetime import datetime

import config
from agent.loop import to_jsonable
from tools import calculator
from tools.registry import Toolset

SYSTEM = "你是报销审核助手。所有计算都必须调用工具完成。"
TASK = ("报销单 C002 里有一笔上海住宿：9 月 22 日入住、9 月 25 日离店，共 2340 元，上海住宿标准每晚 600 元。"
        "请在同一轮里同时调用两个工具：用 calc_days_between 算住宿晚数，用 calc_evaluate 算 2340 - 3*600 的超标金额。"
        "拿到结果后用一句话告诉我住了几晚、超标多少。")

# 只用两个计算工具；关闭 strict，让两种协议收到的参数说明完全相同
TOOLSET = Toolset(name="calc-only", tools=calculator.TOOLS, strict=False)


def show(title, obj):
    print(f"\n----- {title} -----")
    print(json.dumps(to_jsonable(obj), ensure_ascii=False, indent=2))


# ============================================================
# OpenAI 协议
# ============================================================
def run_openai():
    print("\n" + "=" * 30 + " OpenAI 协议 " + "=" * 30)
    client = config.get_openai_client()
    messages = [{"role": "system", "content": SYSTEM},      # ① system 放在 messages 里，作为第一条消息
                {"role": "user", "content": TASK}]
    req = {"model": config.MODEL, "messages": messages, "tools": TOOLSET.openai_tools(), "temperature": 0}
    show("第 1 轮请求", req)
    r1 = client.chat.completions.create(**req, extra_body=config.EXTRA_BODY or None)
    show("第 1 轮响应", r1)

    msg = r1.choices[0].message
    calls = msg.tool_calls or []
    # ② 工具调用在 message.tool_calls 数组里；③ 参数 arguments 是 JSON 字符串，要自己解析
    appended = [{"role": "assistant", "content": msg.content,
                 "tool_calls": [{"id": c.id, "type": "function",
                                 "function": {"name": c.function.name, "arguments": c.function.arguments}} for c in calls]}]
    for c in calls:
        output, _ = TOOLSET.execute(c.function.name, c.function.arguments)
        # ④ 每个结果单独一条 role="tool" 的消息，用 tool_call_id 对应
        appended.append({"role": "tool", "tool_call_id": c.id, "content": output})
    messages += appended
    show("第 2 轮请求里新增的消息（assistant 原样放回 + 每个工具一条 tool 消息）", appended)

    r2 = client.chat.completions.create(**req, extra_body=config.EXTRA_BODY or None)
    show("第 2 轮响应", r2)
    return {"round1_request": req["tools"], "round1_response": to_jsonable(r1),
            "round2_appended": appended, "round2_response": to_jsonable(r2),
            "stop_values": [r1.choices[0].finish_reason, r2.choices[0].finish_reason], "calls_in_one_turn": len(calls)}


# ============================================================
# Anthropic 协议
# ============================================================
def run_anthropic():
    print("\n" + "=" * 30 + " Anthropic 协议 " + "=" * 30)
    client = config.get_anthropic_client()
    messages = [{"role": "user", "content": TASK}]
    req = {"model": config.ANTHROPIC_MODEL, "max_tokens": 1024,   # Anthropic 协议必须传 max_tokens
           "system": SYSTEM,                                       # ① system 是单独的顶层参数，不在 messages 里
           "messages": messages, "tools": TOOLSET.anthropic_tools(), "temperature": 0}
    extra = {"thinking": {"type": "disabled"}} if config.IS_DEEPSEEK else {}
    show("第 1 轮请求", req)
    r1 = client.messages.create(**req, **extra)
    show("第 1 轮响应", r1)

    # ② 回复的 content 是一个"块"数组：文字是 text 块，工具调用是 tool_use 块；③ input 已经是对象，不用 json.loads
    assistant_blocks = [b.model_dump(exclude_none=True) for b in r1.content]
    results = []
    for b in r1.content:
        if b.type == "tool_use":
            output, is_error = TOOLSET.execute(b.name, b.input)
            # ④ 所有工具结果放进同一条 role="user" 的消息，每个是一个 tool_result 块，用 tool_use_id 对应
            results.append({"type": "tool_result", "tool_use_id": b.id, "content": output, "is_error": is_error})
    appended = [{"role": "assistant", "content": assistant_blocks}, {"role": "user", "content": results}]
    messages += appended
    show("第 2 轮请求里新增的消息（assistant 原样放回 + 一条 user 消息装下全部 tool_result）", appended)

    r2 = client.messages.create(**req, **extra)
    show("第 2 轮响应", r2)
    return {"round1_request": req["tools"], "round1_response": to_jsonable(r1),
            "round2_appended": appended, "round2_response": to_jsonable(r2),
            "stop_values": [r1.stop_reason, r2.stop_reason], "calls_in_one_turn": len(results)}


def main():
    out = {}
    for name, fn in (("openai", run_openai), ("anthropic", run_anthropic)):
        try:
            out[name] = fn()
        except Exception as e:
            print(f"\n{name} 协议调用失败：{type(e).__name__}: {e}")
            if name == "anthropic":
                print("如果提示模型名不支持，在 .env 里设置 ANTHROPIC_COMPAT_MODEL（例如 deepseek-flash）后重试")
            out[name] = {"error": f"{type(e).__name__}: {e}"}

    print("\n" + "=" * 72)
    print("本次运行实际观察到的值：")
    for name in out:
        if "error" not in out[name]:
            print(f"  {name:<10} 结束原因（第 1 轮、第 2 轮）= {out[name]['stop_values']}，第 1 轮一次性请求了 {out[name]['calls_in_one_turn']} 个工具")
    print("""
对照表（结合上面打印的 JSON 看）：
  方面            OpenAI 协议                                  Anthropic 协议
  system 提示词   messages 第一条，role="system"               顶层参数 system，不在 messages 里
  工具定义        {"type":"function","function":{...parameters}} {"name","description","input_schema"}
  模型的工具调用  message.tool_calls[]，arguments 是 JSON 字符串  content[] 里的 tool_use 块，input 是对象
  "要用工具"信号  finish_reason = "tool_calls"                    stop_reason = "tool_use"
  回传工具结果    每个结果一条 role="tool" 消息 + tool_call_id    一条 role="user" 消息，内含多个 tool_result 块 + tool_use_id
  并行调用        tool_calls 数组里有多个元素                     content 里有多个 tool_use 块
  标记工具出错    没有专门字段，只能写在 content 文字里           tool_result 有 is_error 字段
  max_tokens      可选                                            必填""")

    config.LOGS_DIR.mkdir(exist_ok=True)
    path = config.LOGS_DIR / f"protocols_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n完整 JSON 已保存：{path}")


if __name__ == "__main__":
    main()
