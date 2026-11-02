"""
用 Pydantic 重写 Day 7 的工具：一个 Pydantic 模型 = 一份参数说明书 + 一个校验器。

Day 7 我们是这样做的：
    1. 手写 JSON Schema（一大段字典）发给模型
    2. 再用 jsonschema 库拿同一份 schema 去校验参数
    3. json.loads 解析参数要单独 try 一次
现在换成 Pydantic：
    1. 用 Python 类型 + Field 写一个类
    2. Model.model_json_schema() 自动生成 JSON Schema 发给模型
    3. Model.model_validate_json(原始字符串) 一步完成"解析 JSON + 校验 + 转成 Python 对象"
好处：schema 和校验永远是同一份来源，不会出现"改了 schema 忘了改校验"的情况；
     而且拿到的是有类型的对象（args.order_id），IDE 能补全，写错字段名会立刻发现。

注意：今天只注册 3 个只读工具。退款这种写操作和人工确认在 Day 7 已经讲过，
     CreateRefundArgs 只在 01 里拿来演示 Field 的数值约束，不会真的执行。
"""
import json
from datetime import date
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from common import load_orders

MAX_OUTPUT = 2000     # 工具结果截断长度（同 Day 7）
REFUND_LIMIT = 1000
REFUND_DAYS = 7
TODAY = date(2026, 10, 17)   # 和 Day 7 一样固定"今天"，让规则判断每次都一样

# Annotated[类型, Field(...)]：把"类型 + 约束"打包成一个可复用的类型别名。
# 下面三个模型都用 OrderId，订单号的格式只需要写一次。
OrderId = Annotated[str, Field(pattern=r"^ORD\d{6}$", description="订单号，格式如 ORD100021")]


# ============================================================
# 1. 参数模型：每个类对应一个工具的参数
# ============================================================
class ToolArgs(BaseModel):
    # extra="forbid"：传了没定义的字段就报错。
    # 生成 JSON Schema 时会变成 "additionalProperties": false（和 Day 7 手写的一样）
    model_config = ConfigDict(extra="forbid")


class SearchOrdersArgs(ToolArgs):
    """按客户邮箱查询订单列表，可以按状态筛选。返回订单号、商品、金额、状态、下单日期。"""
    # 类的 docstring 会变成 schema 里的 "description"，下面直接拿它当工具说明

    # 邮箱：Pydantic 有 EmailStr 类型，但需要额外装 email-validator 包，这里用正则代替
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", description="客户邮箱")
    # Optional[...] = None：可以不传。Literal[...] 会生成 JSON Schema 的 enum
    status: Optional[Literal["paid", "shipped", "delivered", "refunded"]] = Field(
        default=None,
        description="可选。paid 已付款未发货，shipped 已发货，delivered 已签收，refunded 已退款",
    )


class GetOrderArgs(ToolArgs):
    """查询单个订单的详细信息，包括物流进度和客户备注。"""
    order_id: OrderId

    # field_validator：Field 表达不了的规则，用一个函数来写。
    # mode="before" 表示在类型检查之前先执行，这里把 " ord100021 " 规范成 "ORD100021"，
    # 模型偶尔写小写或多空格时就不会白白失败一次
    @field_validator("order_id", mode="before")
    @classmethod
    def normalize(cls, v):
        return v.strip().upper() if isinstance(v, str) else v


class CheckRefundPolicyArgs(ToolArgs):
    """检查订单是否符合退款条件，返回能否退款和原因。"""
    order_id: OrderId


class CreateRefundArgs(ToolArgs):
    """为订单创建退款（今天只用来演示 Field 约束，不注册成工具）。"""
    order_id: OrderId
    amount: float = Field(gt=0, description="退款金额（元），必须大于 0")   # gt=0 → exclusiveMinimum: 0
    reason: Literal["商品损坏", "与描述不符", "未收到货", "七天无理由"]


# ============================================================
# 2. 工具函数：和 Day 7 逻辑相同，只是参数改成接收 Pydantic 对象
# ============================================================
def _find(order_id):
    return next((o for o in load_orders() if o["order_id"] == order_id), None)


def search_orders(args: SearchOrdersArgs):
    rows = [
        {k: o[k] for k in ("order_id", "item", "amount", "status", "order_date")}
        for o in load_orders()
        if o["email"] == args.email and (args.status is None or o["status"] == args.status)
    ]
    return rows or f"没有找到 {args.email} 的订单"


def get_order(args: GetOrderArgs):
    return _find(args.order_id) or f"订单 {args.order_id} 不存在"


def check_refund_policy(args: CheckRefundPolicyArgs):
    order = _find(args.order_id)
    if order is None:
        return {"refundable": False, "reason": f"订单 {args.order_id} 不存在"}
    if order["status"] != "delivered":
        return {"refundable": False, "reason": f"订单状态是 {order['status']}，只有已签收的订单可以退款"}
    days = (TODAY - date.fromisoformat(order["delivered_date"])).days
    if days > REFUND_DAYS:
        return {"refundable": False, "reason": f"已签收 {days} 天，超过 {REFUND_DAYS} 天退款期限"}
    if order["amount"] > REFUND_LIMIT:
        return {"refundable": False, "reason": f"金额 {order['amount']} 元超过 {REFUND_LIMIT} 元，需要转人工"}
    return {"refundable": True, "max_amount": order["amount"], "reason": f"已签收 {days} 天，符合退款条件"}


# 工具注册表：工具名 → (参数模型, 函数)
REGISTRY = {
    "search_orders": (SearchOrdersArgs, search_orders),
    "get_order": (GetOrderArgs, get_order),
    "check_refund_policy": (CheckRefundPolicyArgs, check_refund_policy),
}


def to_openai_tool(name, model):
    """把一个 Pydantic 模型转成 OpenAI 格式的工具定义。
    和 Day 7 手写的结构完全一样，只是 parameters 由 model_json_schema() 自动生成。"""
    return {"type": "function", "function": {
        "name": name,
        "description": model.__doc__.strip(),
        "parameters": model.model_json_schema(),
    }}


TOOLS = [to_openai_tool(name, model) for name, (model, _) in REGISTRY.items()]


# ============================================================
# 3. 执行一次工具调用
#    Day 7 是 5 层：工具名 → json.loads → jsonschema → 执行 → 截断
#    现在 json.loads 和 schema 校验合并成一步 model_validate_json，变成 4 层
# ============================================================
def format_errors(e: ValidationError):
    """把 Pydantic 的报错整理成模型看得懂的短句，例如：order_id: String should match pattern ..."""
    return "; ".join(f"{'.'.join(str(x) for x in err['loc']) or '(整体)'}: {err['msg']}" for err in e.errors())


def execute_tool_call(name, raw_args):
    """返回 (给模型看的文本, 是否被拦截)。任何错误都变成文字交给模型，程序不会崩。"""
    if name not in REGISTRY:
        return f"错误：没有名为 {name} 的工具，可用工具：{list(REGISTRY)}", True
    model, func = REGISTRY[name]
    try:
        # 一步完成：解析 JSON 字符串 + 按模型校验 + 生成 Python 对象
        # JSON 本身坏掉时，错误类型是 json_invalid，也会落到下面的 except 里
        args = model.model_validate_json(raw_args or "{}")
    except ValidationError as e:
        return f"参数校验失败：{format_errors(e)}。请修正参数后重新调用。", True
    try:
        result = func(args)
    except Exception as e:
        return f"工具执行出错：{type(e).__name__}: {e}", True
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + f"\n...[结果过长，已截断，原长度 {len(text)} 字符]"
    return text, False
