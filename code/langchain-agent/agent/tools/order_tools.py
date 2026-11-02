"""
订单和保修工具

【Tools 模块要点】
1. 工具只做薄薄一层：取参数 → 调 service → 把结果整理成给模型看的文字。业务规则都在 services 里。
2. runtime: ToolRuntime[UserContext] 是框架自动传入的，不会出现在发给模型的参数 schema 里，
   模型看不见也填不了。用户身份从 runtime.context 读。
3. get_order_detail 返回 Command：同时做两件事
   - 往 State 写 current_order_id（之后用户说「这台机器」，模型就知道指哪个订单）
   - 写一条 ToolMessage 作为这次工具调用的结果（tool_call_id 必须对上，否则消息链断掉会报错）

【ToolRuntime 里有什么】
    runtime.context       invoke 时传入的 UserContext（user_id、user_name、role）
    runtime.state         当前 State（messages、current_order_id、token_usage）
    runtime.tool_call_id  这次工具调用的 ID（模型生成的），手写 ToolMessage 时必须带上
工具函数的返回值：
    返回 str      → 框架自动包成 ToolMessage(content=返回值, tool_call_id=...)
    返回 Command  → 框架按 update 更新 State，ToolMessage 要自己放进 update["messages"]
抛出的异常：不在这里捕获，由 agent/middleware.py 的 guard_tool_call 统一处理

【重要】@tool 函数的 docstring 就是发给模型的「工具说明」，讲解统一写成 # 注释，不改 docstring。
"""
import json

from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.types import Command

from agent.schemas import CheckWarrantyInput, OrderIdInput
from agent.state import UserContext
from services import order_service, warranty_service


def _brief(order: dict) -> dict:
    """只把模型需要的字段交给它：字段越少，token 越少，也越不容易被无关信息干扰"""
    return {
        "order_id": order["order_id"],
        "product": order["product"],
        "purchase_date": order["purchase_date"],
        "status": order["status"],
    }


# @tool 不带参数：参数 schema 从函数签名推断；这里除了 runtime 没有别的参数，所以模型调用时不用填任何参数
# 返回：订单列表的 JSON 字符串（ensure_ascii=False 让中文原样输出，模型读得懂，也比 \uXXXX 省 token）
@tool
def list_my_orders(runtime: ToolRuntime[UserContext]) -> str:
    """列出当前登录用户的全部订单（订单号、产品、购买日期、状态）。
    用户没有提供订单号、或者说「我买的那台」时先调用它。"""
    orders = order_service.list_orders(runtime.context.user_id)
    if not orders:
        return "当前用户没有订单。"
    return json.dumps([_brief(o) for o in orders], ensure_ascii=False)


# args_schema=OrderIdInput：order_id 必须符合 SO + 8 位数字，不符合时工具不会执行，
#   错误信息作为 ToolMessage 回给模型，模型可以改正后重试（lessons/03 第 2 节演示）
# 返回 Command 而不是 str，见文件开头第 3 点
@tool(args_schema=OrderIdInput)
def get_order_detail(order_id: str, runtime: ToolRuntime[UserContext]) -> Command:
    """查询某个订单的详情和物流进度，并把它设为当前正在处理的订单。"""
    ctx = runtime.context
    # 订单不存在 / 不是自己的 → 这里抛 BusinessError，由 guard_tool_call 转成「操作未完成」
    order = order_service.get_order(order_id, ctx.user_id, ctx.role)

    # 详情比列表多两个字段：序列号和物流轨迹
    detail = _brief(order) | {"serial_no": order["serial_no"], "logistics": order["logistics"]}
    # Command(update={...})：工具执行完后要合并进 State 的内容
    #   "current_order_id"  直接覆盖 State 里的同名字段
    #   "messages"          按 add_messages 规则追加；这条 ToolMessage 就是本次工具调用的结果
    return Command(
        update={
            "current_order_id": order_id,
            "messages": [
                # ToolMessage 的参数：
                #   content       给模型看的内容
                #   tool_call_id  必须等于模型请求工具时的调用 ID，模型靠它把结果和请求对上（lessons/02 第 3 节演示对不上会报 400）
                #   name          工具名
                ToolMessage(
                    content=json.dumps(detail, ensure_ascii=False),
                    tool_call_id=runtime.tool_call_id,
                    name="get_order_detail",
                )
            ],
        }
    )


# args_schema=CheckWarrantyInput：fault_category 只能从 FaultCategory 的 8 个选项里选
# 这个工具不写 current_order_id（只有 get_order_detail 写），所以只查保修后 /state 里「当前订单」仍是暂无
# 返回：warranty_service 计算结果的 JSON，模型必须以它为准，不能自己推算日期
@tool(args_schema=CheckWarrantyInput)
def check_warranty(order_id: str, fault_category: str, runtime: ToolRuntime[UserContext]) -> str:
    """根据订单和故障类型，判断是否在保修期内、是否还能退换货。
    结论由系统按保修规则计算，回答用户时必须以这个结果为准。"""
    ctx = runtime.context
    order = order_service.get_order(order_id, ctx.user_id, ctx.role)
    result = warranty_service.check_warranty(order, fault_category)
    return json.dumps(result, ensure_ascii=False)
