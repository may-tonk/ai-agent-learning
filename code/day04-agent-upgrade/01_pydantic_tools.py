"""
Day 4 · 01：Pydantic（Models、Fields、JSON Schema）

不调用 API，不花钱。目的是看清 Pydantic 在 agent 里的两个用途：
  A. 写一个类 → 自动生成 JSON Schema → 当作工具说明书发给模型
  B. 模型返回的参数字符串 → model_validate_json 一步完成解析和校验

先读 tools.py（工具的 Pydantic 版本），再运行本文件：
    python code/day04-agent-upgrade/01_pydantic_tools.py
"""
import importlib.util
import json
from pathlib import Path

from pydantic import ValidationError

from tools import (TOOLS, CreateRefundArgs, GetOrderArgs, SearchOrdersArgs,
                   execute_tool_call, format_errors)


def title(text):
    print(f"\n{'=' * 70}\n{text}\n{'=' * 70}")


def show(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ------------------------------------------------------------
# 第 1 部分：Model 是什么 —— 一个"带类型检查的数据类"
# ------------------------------------------------------------
title("第 1 部分：创建 Model 对象，看 Pydantic 怎么处理类型")

# amount 传的是字符串 "99.5"，但字段类型是 float。
# Pydantic 默认是"宽松模式"（lax）：能安全转换的就帮你转换，所以这里不会报错
args = CreateRefundArgs(order_id="ORD100021", amount="99.5", reason="商品损坏")
print("创建成功：", repr(args))
print("amount 的类型：", type(args.amount).__name__, "（字符串被转换成了 float）")
print("model_dump()      →", args.model_dump())          # 转回 dict
print("model_dump_json() →", args.model_dump_json())     # 转回 JSON 字符串

# 严格模式（strict=True）：不做任何转换，类型不对就报错
try:
    CreateRefundArgs.model_validate({"order_id": "ORD100021", "amount": "99.5", "reason": "商品损坏"}, strict=True)
except ValidationError as e:
    print("strict=True 时：", format_errors(e))


# ------------------------------------------------------------
# 第 2 部分：自动生成的 JSON Schema vs Day 7 手写的 JSON Schema
# ------------------------------------------------------------
title("第 2 部分：model_json_schema() 和 Day 7 手写 schema 对比")

# 用 importlib 按文件路径加载 Day 7 的 agent.py，拿到它手写的 TOOL_SPECS（不会运行它的 main）
day7_path = Path(__file__).resolve().parents[1] / "day07-order-agent" / "agent.py"
spec = importlib.util.spec_from_file_location("day7_agent", day7_path)
day7 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(day7)

for name, model in [("get_order", GetOrderArgs), ("search_orders", SearchOrdersArgs)]:
    print(f"\n--- {name}：Day 7 手写 ---")
    show(day7.TOOL_SPECS[name]["parameters"])
    print(f"--- {name}：Pydantic 自动生成 ---")
    show(model.model_json_schema())

print("""
观察要点：
  1. 约束都对上了：pattern、enum、required、additionalProperties: false 都自动生成
  2. 多了 "title"：Pydantic 给每个字段加的标题，对模型无害，可以忽略
  3. Optional 字段变成了 anyOf [ {enum...}, {type: null} ]，意思是"可以是这几个值之一，也可以是 null"，
     并且有 "default": null；它不在 required 里，所以模型可以不传
  4. 类的 docstring 变成了顶层 "description"
  5. email 不一样：Day 7 用的是 "format": "email"，这里用正则 pattern。
     Pydantic 的 EmailStr 类型需要额外安装 email-validator 包，为了少装一个包这里用了正则
""")

print("--- create_refund：Field(gt=0) 生成了什么 ---")
show(CreateRefundArgs.model_json_schema()["properties"]["amount"])
print("gt=0 → exclusiveMinimum: 0，和 Day 7 手写的一样")


# ------------------------------------------------------------
# 第 3 部分：model_validate_json —— 模拟模型返回的各种参数字符串
# ------------------------------------------------------------
title("第 3 部分：用 model_validate_json 校验模型返回的 arguments 字符串")

# 每一条都模拟"模型在 tool_calls 里返回的 function.arguments"，它永远是一个 JSON 字符串
cases = [
    (GetOrderArgs, '{"order_id": "ORD100021"}', "正常"),
    (GetOrderArgs, '{"order_id": " ord100021 "}', "小写加空格（field_validator 会规范化）"),
    (GetOrderArgs, '{"order_id": "ORD100021"', "JSON 少了右括号（坏 JSON）"),
    (GetOrderArgs, '{"order_id": "100021"}', "订单号格式错"),
    (GetOrderArgs, '{"order_id": "ORD100021", "verbose": true}', "多了没定义的字段"),
    (SearchOrdersArgs, '{"status": "delivered"}', "缺少必填的 email"),
    (SearchOrdersArgs, '{"email": "bob@example.com", "status": "done"}', "status 不在 enum 里"),
    (CreateRefundArgs, '{"order_id": "ORD100021", "amount": -5, "reason": "商品损坏"}', "金额是负数"),
    (CreateRefundArgs, '{"order_id": "ORD100021", "amount": "99", "reason": "商品损坏"}', "金额写成了字符串 \"99\""),
    (CreateRefundArgs, '{"order_id": "ORD100021", "amount": 0, "reason": "不想要了"}', "金额为 0，原因也不在 enum（两个错误）"),
]
for model, raw, label in cases:
    try:
        obj = model.model_validate_json(raw)
        print(f"[通过] {label}\n       {raw}\n       → {obj!r}")
    except ValidationError as e:
        print(f"[拦截] {label}\n       {raw}")
        for err in e.errors():
            # 每个错误都有：type（错误类型）、loc（哪个字段）、msg（说明）
            print(f"       type={err['type']:<22} loc={err['loc']}  msg={err['msg']}")

print("""
观察要点：
  1. 坏 JSON 的错误类型是 json_invalid —— 解析和校验在同一步里完成，不用再单独 try json.loads
  2. 一次能报出多个错误（最后一条同时报了 amount 和 reason），把它们一起交给模型，模型可以一次改完
  3. 金额 "99" 是字符串也通过了：从 JSON 校验时，宽松模式同样会做安全的类型转换
""")


# ------------------------------------------------------------
# 第 4 部分：完整的工具执行流程（模型最终看到的是什么）
# ------------------------------------------------------------
title("第 4 部分：execute_tool_call —— 模型最终收到的工具结果")

calls = [
    ("get_order", '{"order_id": "ORD100023"}'),
    ("check_refund_policy", '{"order_id": "ORD100048"}'),
    ("get_order", '{"order_id": "100023"}'),
    ("delete_order", '{"order_id": "ORD100023"}'),
]
for name, raw in calls:
    text, blocked = execute_tool_call(name, raw)
    print(f"{'拦截' if blocked else '结果'}  {name}({raw})\n      {text[:160]}")


# ------------------------------------------------------------
# 第 5 部分：最终发给模型的 tools 参数
# ------------------------------------------------------------
title("第 5 部分：发给模型的 tools（取第一个看看）")
show(TOOLS[0])
print(f"\n一共 {len(TOOLS)} 个工具：{[t['function']['name'] for t in TOOLS]}")
