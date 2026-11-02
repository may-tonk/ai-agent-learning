"""
维修工单：创建、查询、改状态

这是项目里唯一会「写数据」的地方，所以规则最多：
1. 只能给自己的、已签收的订单建工单
2. 同一订单同一故障已有未完成的工单时，不重复创建（幂等）
   为什么：模型可能因为重试、用户重复说一遍而再次调用建单工具，不拦就会生成一堆重复工单
3. 只有客服主管能改状态，且状态只能按规定方向流转

【在整体流程里的位置】
agent/tools/ticket_tools.py（create_repair_ticket / get_ticket_status / update_ticket_status）→ 本文件
→ data/runtime/tickets.json
注意：建工单、改状态这两个工具在执行前会先经过人工审批（HumanInTheLoopMiddleware），
      审批通过后才会真正走到这里的 create_ticket / update_status。
"""
from datetime import date, datetime

from services.data_store import read_json, write_json
from services.errors import NotFoundError, PermissionDeniedError, RuleViolationError
from services.order_service import get_order
from services.warranty_service import check_warranty

# 「未完成」的状态：处于这两种状态的工单，同订单同故障不允许再建一张
OPEN_STATUSES = {"待处理", "处理中"}

# 允许的状态流转：当前状态 → 可以改成哪些状态
# 已完成 / 已关闭 是终态，不能再改（集合为空）。想增加流程（比如「待寄回」），在这里加即可
ALLOWED_TRANSITIONS = {
    "待处理": {"处理中", "已关闭"},
    "处理中": {"已完成", "已关闭"},
    "已完成": set(),
    "已关闭": set(),
}


def _load() -> list[dict]:
    """读全部工单；还没有工单文件时返回空列表"""
    return read_json("tickets", default=[])


def _new_ticket_id(tickets: list[dict]) -> str:
    """
    生成新工单号。
    tickets：现有全部工单（用来数今天已经建了几张）
    返回：TK + 日期 8 位 + 当天序号 4 位
    （JSON 文件版的简化做法；真实数据库里用自增主键或发号器，避免多人同时建单撞号）
    """
    # TK + 日期 8 位 + 当天序号 4 位，例如 TK202610230001
    today = datetime.now().strftime("%Y%m%d")
    count_today = sum(1 for t in tickets if t["ticket_id"][2:10] == today)
    return f"TK{today}{count_today + 1:04d}"


def create_ticket(
    user_id: str,
    order_id: str,
    fault_category: str,
    description: str,
    urgency: str = "普通",
    today: date | None = None,
) -> dict:
    """
    创建维修工单。

    user_id：当前登录用户（来自 runtime.context，模型改不了）
    order_id / fault_category / description / urgency：模型按 CreateTicketInput 填的参数
        urgency 取值 "普通" / "加急"
    today：判断保修用的日期，测试时传固定日期；正常运行为 None = 今天
    返回 {"ticket": 工单, "duplicated": 是否是已存在的工单}
    异常：订单不是自己的 → PermissionDeniedError；订单未签收 → RuleViolationError
    """
    order = get_order(order_id, user_id)          # 不是自己的订单会在这里抛 PermissionDeniedError

    if order["status"] != "已签收":
        raise RuleViolationError(f"订单 {order_id} 当前状态为「{order['status']}」，签收后才能报修")

    tickets = _load()

    # 幂等检查：同订单 + 同故障 + 未完成 → 直接返回已有工单，不新建
    for t in tickets:
        if t["order_id"] == order_id and t["fault_category"] == fault_category and t["status"] in OPEN_STATUSES:
            return {"ticket": t, "duplicated": True}

    warranty = check_warranty(order, fault_category, today=today)
    ticket = {
        "ticket_id": _new_ticket_id(tickets),
        "order_id": order_id,
        "user_id": user_id,
        "product": order["product"],
        "fault_category": fault_category,
        "description": description,
        "urgency": urgency,
        "in_warranty": warranty["in_warranty"],
        # 收费方式由保修结果决定，不让模型自己说
        "charge_type": "保修内免费" if warranty["in_warranty"] else "保外付费维修",
        "status": "待处理",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        # 状态变更记录：update_status 每改一次追加一条
        "history": [],
    }
    tickets.append(ticket)
    write_json("tickets", tickets)
    return {"ticket": ticket, "duplicated": False}


def get_ticket(ticket_id: str, user_id: str, role: str = "customer") -> dict:
    """
    查单个工单。
    role：customer 只能查自己的；supervisor 可以查所有
    返回：工单字典；异常：不存在 → NotFoundError，不是自己的 → PermissionDeniedError
    """
    for t in _load():
        if t["ticket_id"] == ticket_id:
            if t["user_id"] != user_id and role != "supervisor":
                raise PermissionDeniedError(f"工单 {ticket_id} 不属于当前用户")
            return t
    raise NotFoundError(f"工单 {ticket_id} 不存在")


def list_tickets(user_id: str) -> list[dict]:
    """某个用户的全部工单（目前没有工具用到，留给以后的「我的工单」页面）"""
    return [t for t in _load() if t["user_id"] == user_id]


def update_status(ticket_id: str, new_status: str, operator_id: str, role: str, note: str = "") -> dict:
    """
    修改工单状态（仅客服主管）。

    ticket_id：工单号
    new_status：新状态，必须在 ALLOWED_TRANSITIONS[当前状态] 里
    operator_id：操作人（当前登录用户的 user_id），写进 history 备查
    role：当前用户角色，不是 supervisor 直接拒绝
    note：处理备注
    返回：更新后的工单
    异常：不是主管 → PermissionDeniedError；流转不合法 → RuleViolationError；不存在 → NotFoundError
    """
    # 第二道权限检查：就算模型看见了这个工具（比如配置写错），普通用户也改不了
    if role != "supervisor":
        raise PermissionDeniedError("只有客服主管可以修改工单状态")

    tickets = _load()
    for t in tickets:
        if t["ticket_id"] == ticket_id:
            if new_status not in ALLOWED_TRANSITIONS[t["status"]]:
                raise RuleViolationError(f"工单状态不能从「{t['status']}」改为「{new_status}」")
            t["history"].append(
                {
                    "time": datetime.now().isoformat(timespec="seconds"),
                    "operator": operator_id,
                    "from": t["status"],
                    "to": new_status,
                    "note": note,
                }
            )
            t["status"] = new_status
            write_json("tickets", tickets)
            return t
    raise NotFoundError(f"工单 {ticket_id} 不存在")
