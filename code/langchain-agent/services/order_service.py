"""
订单查询

关键点：每个函数都要传 user_id，并在这里检查「订单是不是这个用户的」。
user_id 来自程序（登录信息），不是模型填的 —— 就算模型被用户诱导传了别人的订单号，这里也会拦下。

【在整体流程里的位置】
agent/tools/order_tools.py（list_my_orders / get_order_detail / check_warranty）→ 本文件 → data/orders.json
services/ticket_service.py 建工单前也会调用 get_order 校验订单归属和状态。
"""
from services.data_store import read_json
from services.errors import NotFoundError, PermissionDeniedError


def _all_orders() -> list[dict]:
    """读全部订单（内部用，不做权限过滤，所以不对外暴露）"""
    return read_json("orders", default=[])


def list_orders(user_id: str) -> list[dict]:
    """
    某个用户的全部订单（按下单时间从新到旧）
    user_id：当前登录用户，来自 runtime.context
    返回：订单字典列表（完整字段；交给模型前由工具层 _brief 精简）
    """
    orders = [o for o in _all_orders() if o["user_id"] == user_id]
    # purchase_date 是 "YYYY-MM-DD" 字符串，按字符串排序就等于按日期排序
    return sorted(orders, key=lambda o: o["purchase_date"], reverse=True)


def get_order(order_id: str, user_id: str, role: str = "customer") -> dict:
    """
    查单个订单。
    order_id：订单号（模型填的，已经过 Pydantic 格式校验，但归属必须在这里查）
    user_id：当前登录用户
    role：customer = 只能查自己的；supervisor = 客服主管，可以查任何人的
    返回：订单字典（含 serial_no、logistics 等全部字段）
    - 订单不存在 → NotFoundError
    - 订单不属于这个用户，且不是客服主管 → PermissionDeniedError
    """
    for order in _all_orders():
        if order["order_id"] == order_id:
            if order["user_id"] != user_id and role != "supervisor":
                # 真实系统里这里还要记一条安全审计日志
                raise PermissionDeniedError(f"订单 {order_id} 不属于当前用户")
            return order
    raise NotFoundError(f"订单 {order_id} 不存在")
