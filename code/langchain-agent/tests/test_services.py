"""业务规则测试：不涉及模型，规则写在代码里，就能用普通单元测试保证它一直正确"""
from datetime import date

import pytest

from services import order_service, ticket_service, warranty_service
from services.errors import NotFoundError, PermissionDeniedError, RuleViolationError


def test_list_orders_only_returns_own_orders():
    orders = order_service.list_orders("U1001")
    assert {o["user_id"] for o in orders} == {"U1001"}
    assert [o["order_id"] for o in orders][0] == "SO20261018"  # 按日期从新到旧


def test_cannot_read_other_users_order():
    with pytest.raises(PermissionDeniedError):
        order_service.get_order("SO20250601", "U1001")


def test_supervisor_can_read_any_order():
    assert order_service.get_order("SO20250601", "S9001", role="supervisor")["user_id"] == "U1002"


def test_unknown_order():
    with pytest.raises(NotFoundError):
        order_service.get_order("SO99999999", "U1001")


@pytest.mark.parametrize(
    "fault, today, expected",
    [
        ("吸力下降", date(2026, 10, 15), True),          # 2025-10-15 购买，主机 12 个月，最后一天仍在保
        ("吸力下降", date(2026, 10, 16), False),         # 第二天过保
        ("导航迷路或建图异常", date(2026, 10, 23), True),  # 激光雷达保 24 个月
        ("滚刷边刷损坏", date(2025, 10, 20), False),      # 耗材不保
    ],
)
def test_warranty_rules(fault, today, expected):
    order = order_service.get_order("SO20251015", "U1001")
    assert warranty_service.check_warranty(order, fault, today=today)["in_warranty"] is expected


def test_return_and_exchange_window():
    order = order_service.get_order("SO20261018", "U1001")  # 2026-10-18 购买
    result = warranty_service.check_warranty(order, "其他", today=date(2026, 10, 23))
    assert result["can_return"] and result["can_exchange"]


def test_ticket_requires_delivered_order():
    with pytest.raises(RuleViolationError):
        ticket_service.create_ticket("U1001", "SO20261018", "拖地漏水", "还没收到就想报修")  # 运输中


def test_ticket_is_idempotent():
    first = ticket_service.create_ticket("U1001", "SO20260312", "拖地漏水", "拖地时一直漏水")
    second = ticket_service.create_ticket("U1001", "SO20260312", "拖地漏水", "又漏了")
    assert not first["duplicated"] and second["duplicated"]
    assert first["ticket"]["ticket_id"] == second["ticket"]["ticket_id"]
    assert len(ticket_service.list_tickets("U1001")) == 1


def test_out_of_warranty_ticket_is_paid():
    t = ticket_service.create_ticket("U1002", "SO20250601", "吸力下降", "吸力明显变小", today=date(2026, 10, 23))
    assert t["ticket"]["charge_type"] == "保外付费维修"


def test_only_supervisor_can_update_status():
    tid = ticket_service.create_ticket("U1001", "SO20260312", "拖地漏水", "拖地时一直漏水")["ticket"]["ticket_id"]
    with pytest.raises(PermissionDeniedError):
        ticket_service.update_status(tid, "处理中", "U1001", "customer")
    assert ticket_service.update_status(tid, "处理中", "S9001", "supervisor")["status"] == "处理中"
    with pytest.raises(RuleViolationError):
        ticket_service.update_status(tid, "待处理", "S9001", "supervisor")  # 不能倒退
