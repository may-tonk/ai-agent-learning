"""
把 Pydantic 生成的 JSON Schema 改成"严格模式"能接受的样子（Day 4 的 02 里写过同样的函数，这里移到公共模块复用）。

严格模式（strict: true）是什么：服务端在生成参数时按 schema 做约束，
保证字段名、类型、枚举值一定合法，不会出现"模型多写了一个字段""数字写成了字符串"。
OpenAI 和 DeepSeek（Beta）都支持，要求也一样：
  - 每个 object 的所有字段都必须列在 required 里（可选字段要写成"可以是 null"）
  - 每个 object 都要 additionalProperties: false
  - 不支持 minLength/maxLength/minItems/maxItems 这类约束（这些交给 Pydantic 在本地校验）
另外这里把 $ref 引用全部展开成内联结构，避免不同服务商对 $ref 支持程度不同。
"""
import copy

UNSUPPORTED = ("minLength", "maxLength", "minItems", "maxItems", "default", "title")


def to_strict_schema(schema):
    schema = copy.deepcopy(schema)
    defs = schema.pop("$defs", {})

    def fix(node):
        if isinstance(node, list):
            return [fix(x) for x in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:                       # "#/$defs/ItemFinding" → 换成 ItemFinding 的完整定义
            name = node["$ref"].split("/")[-1]
            return fix(copy.deepcopy(defs[name]))
        node = {k: v for k, v in node.items() if k not in UNSUPPORTED}
        if node.get("type") == "object":
            node["properties"] = {k: fix(v) for k, v in node.get("properties", {}).items()}
            node["required"] = list(node["properties"])
            node["additionalProperties"] = False
        for key in ("items", "anyOf"):
            if key in node:
                node[key] = fix(node[key])
        return node

    return fix(schema)
