"""
保修判断：完全由代码按规则计算，不交给模型

为什么：「2025-10-15 买的，主机保修 12 个月，今天 2026-10-23 还在不在保」这种日期计算，
模型经常算错，而且算错了会直接影响用户要不要付钱。规则明确的事情交给代码，模型只负责把结果讲清楚。

【在整体流程里的位置】
agent/tools/order_tools.check_warranty → 本文件 → data/warranty_rules.json
services/ticket_service.create_ticket 也会调用它，决定工单是「保修内免费」还是「保外付费」。
保修规则（各部件保修几个月、故障类型对应哪个部件、几天内可退换）都在 data/warranty_rules.json，
改规则改 json 即可，不用改代码。
"""
from datetime import date

from services.data_store import read_json


def _add_months(start: date, months: int) -> date:
    """
    日期加 N 个月；目标月份没有这一天时（如 1 月 31 日 + 1 个月）取该月最后一天
    为什么不用 timedelta(days=30*N)：每个月天数不同，按 30 天算会有几天误差，保修截止日就错了
    """
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    # 从原来的「日」开始试，不合法就依次退到 30、29、28 号
    for day in (start.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise ValueError("日期计算失败")


def check_warranty(order: dict, fault_category: str, today: date | None = None) -> dict:
    """
    返回一个字典，所有结论都是算出来的，工具把它原样交给模型。
    today 参数：正常运行时用今天；测试时可以传固定日期，保证测试结果不随时间变化。

    order：订单字典（调用方已经通过 order_service.get_order 校验过归属）
    fault_category：故障类型，取值见 agent/schemas.py 的 FaultCategory（如 "拖地漏水"）
    返回的字段：
        part              故障对应的部件（主机 / 电池 / 激光雷达 / 耗材）
        warranty_months   该部件保修几个月（耗材为 0）
        expire_date       保修截止日 YYYY-MM-DD
        in_warranty       今天是否在保（True / False）
        reason            一句话结论，模型可以直接转述
        can_return / can_exchange  是否还在退货 / 换货期内
        exclusions        不保修的情况（人为损坏、进水等），提醒用户用
    """
    rules = read_json("warranty_rules", default={})
    today = today or date.today()
    purchase = date.fromisoformat(order["purchase_date"])
    days_since_purchase = (today - purchase).days

    # 故障类型 → 部件（对照表在 warranty_rules.json 的 fault_to_part）；万一表里没登记，兜底按主机算
    part = rules["fault_to_part"].get(fault_category, "主机")
    months = rules["parts"][part]["months"]
    expire = _add_months(purchase, months)
    # 截止日当天仍算在保（<=）
    in_warranty = months > 0 and today <= expire

    if months == 0:
        reason = f"{part}属于易耗品，不在保修范围，可付费购买配件更换"
    elif in_warranty:
        reason = f"{part}保修 {months} 个月，保修期至 {expire.isoformat()}，目前在保修期内"
    else:
        reason = f"{part}保修 {months} 个月，已于 {expire.isoformat()} 过保，可提供付费维修"

    return {
        "order_id": order["order_id"],
        "product": order["product"],
        "purchase_date": order["purchase_date"],
        "fault_category": fault_category,
        "part": part,
        "warranty_months": months,
        "expire_date": expire.isoformat(),
        "in_warranty": in_warranty,
        "reason": reason,
        # 购买 7 天内可退货、15 天内可换货：这类时间窗口也在代码里算好
        "can_return": 0 <= days_since_purchase <= rules["return_days"],
        "can_exchange": 0 <= days_since_purchase <= rules["exchange_days"],
        "exclusions": rules["exclusions"],
    }
