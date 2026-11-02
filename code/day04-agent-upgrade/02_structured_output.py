"""
Day 4 · 02：结构化输出（JSON 模式 + Pydantic 校验 + 失败重试）

先读 ticket.py 顶部的说明，再运行：
    python code/day04-agent-upgrade/02_structured_output.py          # 分析前 4 条工单
    python code/day04-agent-upgrade/02_structured_output.py --all    # 分析全部 10 条
    python code/day04-agent-upgrade/02_structured_output.py --only D # 只运行 D 部分（也可以 --only B 等）

一共 4 个部分：
  A. 不开 JSON 模式，只在提示词里说"用 JSON 回答"：看看 json.loads 能不能直接解析
  B. JSON 模式 + Pydantic：真正的工单分析，代码根据字段决定怎么分流
  C. 重试机制：人为放一个错误答案进对话，看模型收到错误提示后能不能改对
  D. 严格模式工具调用（DeepSeek Beta）：把输出结构伪装成一个工具，让服务端按 schema 约束生成
"""
import argparse
import copy
import json

from openai import APIError

from common import EXTRA_BODY, MODEL, TICKETS, get_client
from ticket import TicketAnalysis, TicketParseError, analyze_ticket, build_messages, check


def title(text):
    print(f"\n{'=' * 70}\n{text}\n{'=' * 70}")


def part_a(client):
    title("A. 不开 JSON 模式：只在提示词里要求 JSON")
    prompt = f"分析这条客服消息的意图、情绪和紧急程度（1-5），用 JSON 格式回答：{TICKETS[2]}"
    resp = client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": prompt}],
                                          max_tokens=300, temperature=0, extra_body=EXTRA_BODY)
    content = resp.choices[0].message.content
    print(f"模型原始输出：\n{content}\n")
    try:
        print("json.loads 成功：", json.loads(content))
    except json.JSONDecodeError as e:
        print(f"json.loads 失败：{e}")
        print("原因通常是：模型在 JSON 外面包了 ```json 代码块，或者前后加了解释文字。")
    print("另外，字段名也是模型自己起的（每次可能不一样），程序没法稳定地读取。")


def route(a):
    """结构化输出的意义：代码可以直接根据字段做决定，不用再去理解一段文字。"""
    if a.needs_human:
        return "转人工"
    if a.urgency >= 4 or a.sentiment == "negative":
        return "agent 优先处理"
    return "agent 正常处理"


def part_b(client, tickets):
    title(f"B. JSON 模式 + Pydantic 校验：分析 {len(tickets)} 条工单")
    total_p = total_c = 0
    for i, text in enumerate(tickets, 1):
        print(f"\n[{i}] 客户：{text}")
        try:
            r = analyze_ticket(client, text, verbose=True)
        except TicketParseError as e:
            print(f"  最终失败：{e}")
            continue
        a = r.analysis   # 这是一个 TicketAnalysis 对象，字段都有类型，可以直接 a.urgency
        print(f"  → 意图={a.intent} 订单={a.order_id} 情绪={a.sentiment} 紧急={a.urgency} "
              f"转人工={a.needs_human}\n  → 摘要：{a.summary}")
        print(f"  → 分流：{route(a)}   （第 {r.attempts} 次成功，tokens 输入 {r.prompt_tokens} / 输出 {r.completion_tokens}）")
        total_p += r.prompt_tokens
        total_c += r.completion_tokens
    print(f"\n合计 tokens：输入 {total_p}，输出 {total_c}")
    print("观察：每条的输入 token 都差不多，因为大头是 system 里的 JSON Schema，每次请求都要重新发送（05 会讲缓存怎么让这部分变便宜）。")


def part_c(client):
    title("C. 重试机制：故意放一个不合格的答案，看模型能不能根据错误提示改正")
    text = TICKETS[0]
    # 人为构造一个"上一轮模型的错误输出"：intent 不在枚举里、urgency 超出 1~5、缺少 needs_human 和 summary
    bad = json.dumps({"intent": "退货", "order_id": "ORD100021", "sentiment": "negative", "urgency": 9},
                     ensure_ascii=False)
    _, feedback = check(bad)
    print(f"客户：{text}\n假设模型第 1 次输出：{bad}\n代码校验后发给模型的提示：{feedback}\n")

    messages = build_messages(text) + [{"role": "assistant", "content": bad},
                                       {"role": "user", "content": feedback}]
    resp = client.chat.completions.create(model=MODEL, messages=messages,
                                          response_format={"type": "json_object"}, max_tokens=300, temperature=0,
                                          extra_body=EXTRA_BODY)
    content = resp.choices[0].message.content
    analysis, feedback2 = check(content)
    print(f"模型第 2 次输出：{content}")
    print(f"校验：{'通过 → ' + repr(analysis) if analysis else feedback2}")


# ============================================================
# D. 严格模式工具调用
#    DeepSeek 的 response_format 不支持 json_schema，但工具调用支持 strict 模式（Beta）：
#    https://api-docs.deepseek.com/guides/tool_calls
#    思路：定义一个"提交分析结果"的工具，参数就是 TicketAnalysis 的结构，再强制模型必须调用它。
#    模型填进去的参数 = 我们要的结构化结果，而且服务端会按 schema 约束生成。
# ============================================================
BETA_BASE_URL = "https://api.deepseek.com/beta"    # Beta 功能必须走这个地址

# 严格模式不支持的关键字（按文档）：字符串的长度、数组的元素个数
UNSUPPORTED = ("minLength", "maxLength", "minItems", "maxItems")


def to_strict_schema(schema):
    """把 Pydantic 生成的 schema 改成严格模式能接受的样子，返回 (新 schema, 改动说明列表)。
    严格模式的要求：每个 object 的所有字段都必须在 required 里，additionalProperties 必须是 false。"""
    schema = copy.deepcopy(schema)     # 深拷贝，不改动原来的 schema
    changes = []

    def fix(node, path):
        if isinstance(node, list):
            for i, item in enumerate(node):
                fix(item, f"{path}[{i}]")
            return
        if not isinstance(node, dict):
            return
        for key in UNSUPPORTED:
            if key in node:
                changes.append(f"删除 {path}.{key}={node.pop(key)}（严格模式不支持，交给 Pydantic 校验）")
        if "default" in node:
            changes.append(f"删除 {path}.default（所有字段都必须填，默认值没有意义）")
            node.pop("default")
        node.pop("title", None)        # Pydantic 自动加的标题，对模型没用，去掉让 schema 更短
        if node.get("type") == "object":
            props = list(node.get("properties", {}))
            missing = [p for p in props if p not in node.get("required", [])]
            if missing:
                changes.append(f"把 {missing} 加入 {path}.required（可选字段改为必填，但仍然可以填 null）")
            node["required"] = props
            node["additionalProperties"] = False
            for name, sub in node.get("properties", {}).items():
                fix(sub, f"{path}.{name}")
        for key in ("anyOf", "items", "$defs"):
            if key in node:
                fix(node[key], f"{path}.{key}")

    fix(schema, "root")
    return schema, changes


def part_d(client, tickets):
    title("D. 严格模式工具调用（DeepSeek Beta）")
    strict_schema, changes = to_strict_schema(TicketAnalysis.model_json_schema())
    print("把 Pydantic 的 schema 改成严格模式能接受的样子，改动如下：")
    for c in changes:
        print(f"  - {c}")
    print(f"改好的 schema：\n{json.dumps(strict_schema, ensure_ascii=False, indent=2)}")

    submit_tool = {"type": "function", "function": {
        "name": "submit_analysis",
        "description": "提交对客户消息的分析结果",
        "strict": True,                         # 开启严格模式
        "parameters": strict_schema,
    }}
    # with_options：复制一个客户端，只把 base_url 换成 Beta 地址，API key 等其他配置不变
    beta = client.with_options(base_url=BETA_BASE_URL)

    total_p = total_c = 0
    for i, text in enumerate(tickets, 1):
        print(f"\n[{i}] 客户：{text}")
        try:
            resp = beta.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": "你是电商客服系统的工单分析器。分析客户消息，然后调用 submit_analysis 提交结果。"},
                          {"role": "user", "content": text}],
                tools=[submit_tool],
                # tool_choice 指定函数名 = 强制模型必须调用这个工具，不能直接回复文字
                tool_choice={"type": "function", "function": {"name": "submit_analysis"}},
                temperature=0,
                extra_body=EXTRA_BODY,   # 思考模式不支持指定 tool_choice，必须关掉
            )
        except APIError as e:
            # 如果 schema 里有严格模式不支持的写法，服务端会在这里直接拒绝
            print(f"  服务端拒绝：{type(e).__name__}: {e}")
            return
        msg = resp.choices[0].message
        if not msg.tool_calls:
            print(f"  模型没有调用工具，而是回复了：{msg.content}")
            continue
        raw = msg.tool_calls[0].function.arguments
        print(f"  工具参数原文：{raw}")
        # 严格模式下结构一定对，但 summary 的 40 字上限服务端不管，所以 Pydantic 校验仍然要做
        analysis, feedback = check(raw)
        print(f"  Pydantic 校验：{'通过' if analysis else feedback}")
        print(f"  tokens：输入 {resp.usage.prompt_tokens} / 输出 {resp.usage.completion_tokens}")
        total_p += resp.usage.prompt_tokens
        total_c += resp.usage.completion_tokens
    print(f"\n合计 tokens：输入 {total_p}，输出 {total_c}（可以和 B 部分的合计对比）")
    print("""
和 B 部分（JSON 模式）对比：
  - B：schema 写在提示词里，服务端只保证"是合法 JSON"，字段对不对靠模型自觉 + Pydantic 兜底 + 重试
  - D：schema 放在工具定义里，服务端按 schema 约束生成，字段名、枚举值、类型一定对；
       但 maxLength 这类不支持的约束还是要靠 Pydantic，而且这是 Beta 功能，生产环境要留好兜底""")


def main(client=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="分析全部 10 条工单")
    parser.add_argument("--only", choices=["A", "B", "C", "D"], help="只运行某一个部分")
    args = parser.parse_args()
    client = client or get_client()
    tickets = TICKETS if args.all else TICKETS[:4]
    if args.only in (None, "A"):
        part_a(client)
    if args.only in (None, "B"):
        part_b(client, tickets)
    if args.only in (None, "C"):
        part_c(client)
    if args.only in (None, "D"):
        part_d(client, tickets)


if __name__ == "__main__":
    main()
