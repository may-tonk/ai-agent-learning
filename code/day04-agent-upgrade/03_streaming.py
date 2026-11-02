"""
Day 4 · 03：流式输出（streaming）

为什么要流式：模型是一个 token 一个 token 生成的。不开流式时，要等全部生成完才一次性返回，
用户盯着空白等好几秒；开了流式，服务端每生成一小段就推过来，用户马上能看到字往外蹦。
总耗时几乎不变，但"第一个字出现的时间"（TTFT，time to first token）短得多，体验完全不同。

运行：
    python code/day04-agent-upgrade/03_streaming.py

A. 同一个问题，非流式 vs 流式：对比"第一个字出现的时间"和"总耗时"
B. 流式 + 工具调用：tool_calls 也是被拆成碎片一点点发过来的，要自己按 index 拼回完整的调用
"""
import time

from common import EXTRA_BODY, MODEL, get_client
from tools import TOOLS, execute_tool_call

MAX_STEPS = 6


def title(text):
    print(f"\n{'=' * 70}\n{text}\n{'=' * 70}")


# ============================================================
# A. 非流式 vs 流式
# ============================================================
def part_a(client):
    title("A. 非流式 vs 流式")
    messages = [{"role": "user", "content": "用 150 字左右，向客户解释我们店的退款规则："
                 "签收 7 天内、金额 1000 元以内可以由客服直接退款，超过的需要转人工审核。"}]

    # ---- 非流式：create() 会一直等到全部生成完才返回 ----
    t0 = time.perf_counter()
    resp = client.chat.completions.create(model=MODEL, messages=messages, max_tokens=400, extra_body=EXTRA_BODY)
    total = time.perf_counter() - t0
    print(f"[非流式] 等了 {total:.2f} 秒才看到内容，然后一次性打印：\n{resp.choices[0].message.content}")
    print(f"[非流式] 总耗时 {total:.2f}s，输出 {resp.usage.completion_tokens} tokens")

    # ---- 流式：stream=True 后，create() 立刻返回一个"迭代器"，for 循环每次拿到一个 chunk ----
    print("\n[流式] 内容一边生成一边打印：")
    t0 = time.perf_counter()
    first = None
    chunks = 0
    usage = None
    stream = client.chat.completions.create(
        model=MODEL, messages=messages, max_tokens=400, stream=True,
        # 流式默认不返回 usage；加上这个，最后会多发一个 chunk 专门带 usage（它的 choices 是空列表）
        stream_options={"include_usage": True},
        extra_body=EXTRA_BODY,
    )
    for chunk in stream:
        chunks += 1
        if chunk.usage:
            usage = chunk.usage
        if not chunk.choices:          # 最后那个 usage chunk 没有 choices，跳过
            continue
        piece = chunk.choices[0].delta.content   # 注意：流式里是 delta（增量），不是 message
        if piece:
            if first is None:
                first = time.perf_counter() - t0
            print(piece, end="", flush=True)     # flush=True：立刻显示，不等缓冲区满
    total = time.perf_counter() - t0
    print(f"\n[流式] 第一个字在 {first:.2f}s 出现，总耗时 {total:.2f}s，一共收到 {chunks} 个 chunk")
    if usage:
        print(f"[流式] usage：输入 {usage.prompt_tokens}，输出 {usage.completion_tokens} tokens")
    print("观察：两种方式总耗时差不多，但流式的第一个字出现得早得多。")


# ============================================================
# B. 流式 + 工具调用
# ============================================================
def stream_one_step(client, messages, raw_budget):
    """发一次流式请求，边收边处理。返回 (文字内容, 拼好的工具调用列表, finish_reason, usage, 剩余可打印碎片数)。"""
    stream = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS,
                                            stream=True, stream_options={"include_usage": True}, extra_body=EXTRA_BODY)
    text_parts = []
    calls = {}          # index → {"id", "name", "arguments"}；用 index 区分并行的多个工具调用
    finish_reason = usage = None
    for chunk in stream:
        if chunk.usage:
            usage = chunk.usage
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        delta = choice.delta
        if delta.content:
            print(delta.content, end="", flush=True)
            text_parts.append(delta.content)
        # 工具调用的碎片：第一个碎片带 id 和函数名，后面的碎片只带 arguments 的一小段字符串
        for tc in delta.tool_calls or []:
            if raw_budget > 0:
                if text_parts and not calls:
                    print()     # 前面流式打印的文字没有换行，先换一行，不然第一个碎片会接在文字后面
                print(f"    碎片 index={tc.index} id={tc.id} name={tc.function.name if tc.function else None} "
                      f"arguments片段={tc.function.arguments if tc.function else None!r}")
                raw_budget -= 1
            slot = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
            if tc.id:
                slot["id"] = tc.id
            if tc.function and tc.function.name:
                slot["name"] += tc.function.name
            if tc.function and tc.function.arguments:
                slot["arguments"] += tc.function.arguments   # 字符串一段段接起来，接完才是完整 JSON
        if choice.finish_reason:
            finish_reason = choice.finish_reason
    return "".join(text_parts), [calls[i] for i in sorted(calls)], finish_reason, usage, raw_budget


def part_b(client):
    title("B. 流式 + 工具调用：边收碎片边拼装")
    question = "我是 alice@example.com，帮我看看我所有订单的情况，有没有可以退款的？"
    print(f"客户：{question}")
    messages = [
        {"role": "system", "content": "你是电商客服，用工具查询订单和退款规则后再回答，回答简洁。"},
        {"role": "user", "content": question},
    ]
    raw_budget = 15     # 只打印前 15 个工具调用碎片，看清楚样子就够了，不然会刷屏
    for step in range(1, MAX_STEPS + 1):
        print(f"\n--- 第 {step} 步（流式请求）---")
        text, calls, finish_reason, usage, raw_budget = stream_one_step(client, messages, raw_budget)
        if usage:
            print(f"\n    [finish_reason={finish_reason}，输入 {usage.prompt_tokens} / 输出 {usage.completion_tokens} tokens]")

        # 把拼好的结果放回历史，格式和非流式时 message 的结构一样
        assistant = {"role": "assistant", "content": text or None}
        if calls:
            assistant["tool_calls"] = [{"id": c["id"], "type": "function",
                                        "function": {"name": c["name"], "arguments": c["arguments"]}}
                                       for c in calls]
        messages.append(assistant)

        if not calls:          # 没有工具调用 = 最终回答（上面已经流式打印出来了）
            return
        for c in calls:
            print(f"    拼装完成 → {c['name']}({c['arguments']})")
            result, blocked = execute_tool_call(c["name"], c["arguments"])
            print(f"    {'拦截' if blocked else '结果'}：{result[:120]}")
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})
    print(f"\n达到最大步数 {MAX_STEPS}，停止")


def main(client=None):
    client = client or get_client()
    part_a(client)
    part_b(client)
    print("\n观察要点：tool_calls 的 arguments 是被切成很多小段发来的，单独一段不是合法 JSON，"
          "必须按 index 全部接完才能解析。所以流式 agent 一般是：文字实时显示，工具调用收完整再执行。")


if __name__ == "__main__":
    main()
