"""
维修工单工具

【Tools 模块要点】
- create_repair_ticket / update_ticket_status 会写数据，在 config/agent.yml 里登记为「需要人工审批」，
  HumanInTheLoopMiddleware 会在它们真正执行之前暂停，等客服确认（见 agent/agent.py）。
- get_ticket_status 设置了 return_direct=True：工具结果直接作为最终回答返回给用户，
  不再交给模型润色一遍 —— 工单状态是固定格式的事实，省一次模型调用，也避免模型改写信息。

【在整体流程里的位置】模型请求工具 →（写数据的工具先经过人工审批）→ 本文件 → services/ticket_service.py
→ data/runtime/tickets.json

【重要】@tool 函数的 docstring 就是发给模型的「工具说明」，讲解统一写成 # 注释，不改 docstring。
"""
import json

from langchain.tools import ToolRuntime, tool

from agent.schemas import CreateTicketInput, TicketIdInput, UpdateTicketInput
from agent.state import UserContext
from services import ticket_service


# args_schema=CreateTicketInput：订单号格式、故障类型枚举、描述长度、urgency 默认值都在里面
# 执行前会被 HumanInTheLoopMiddleware 暂停：客服批准才会真正执行这个函数；拒绝则不执行，拒绝理由回给模型
# docstring 里写了「什么时候才能调用」—— 这是在用工具说明约束模型行为（配合系统提示词里的报修流程）
# 返回：新工单的关键字段 JSON；如果是重复工单，返回一句说明
@tool(args_schema=CreateTicketInput)
def create_repair_ticket(
    order_id: str,
    fault_category: str,
    description: str,
    urgency: str,
    runtime: ToolRuntime[UserContext],
) -> str:
    """为用户的故障机器创建维修工单。
    只有在用户明确表示要报修、且已经确认订单号和故障现象之后才调用。
    是否免费由系统按保修规则决定。"""
    # user_id 来自 runtime.context，不是模型参数：模型没法替别人建工单
    result = ticket_service.create_ticket(
        user_id=runtime.context.user_id,
        order_id=order_id,
        fault_category=fault_category,
        description=description,
        urgency=urgency,
    )
    ticket = result["ticket"]
    if result["duplicated"]:
        return (
            f"该订单的同类故障已有未完成的工单 {ticket['ticket_id']}（状态：{ticket['status']}），"
            f"没有重复创建。"
        )
    # 只挑模型需要的字段返回，user_id、history 等内部字段不给模型
    return json.dumps(
        {k: ticket[k] for k in ("ticket_id", "order_id", "fault_category", "urgency", "charge_type", "status")},
        ensure_ascii=False,
    )


# return_direct=True：这个工具的返回值直接成为本轮最终回答，agent 不会再调用一次模型
#   适合：结果格式固定、不需要模型再加工的工具；需要模型分析结果的工具不要用
#   agent/agent.py 的 CustomerServiceSession._run 会把它作为 ("final", 文本) 事件交给界面显示
# 返回：多行纯文本（直接给用户看，所以不是 JSON）
@tool(args_schema=TicketIdInput, return_direct=True)
def get_ticket_status(ticket_id: str, runtime: ToolRuntime[UserContext]) -> str:
    """查询维修工单的当前状态和处理记录。"""
    ctx = runtime.context
    t = ticket_service.get_ticket(ticket_id, ctx.user_id, ctx.role)

    lines = [
        f"工单 {t['ticket_id']}｜{t['product']}｜{t['fault_category']}",
        f"当前状态：{t['status']}（{t['charge_type']}，{t['urgency']}）",
    ]
    # 每次状态变更一行：时间 原状态 → 新状态 备注
    for h in t["history"]:
        lines.append(f"  {h['time']} {h['from']} → {h['to']} {h['note']}")
    return "\n".join(lines)


# 两道防线：① config/agent.yml 的 role_tools 里普通用户没有它，模型根本看不到（filter_tools_by_role）
#           ② ticket_service.update_status 里再检查一次 role
# 同时它也需要人工审批（approval_required_tools）
@tool(args_schema=UpdateTicketInput)
def update_ticket_status(
    ticket_id: str, new_status: str, note: str, runtime: ToolRuntime[UserContext]
) -> str:
    """（仅客服主管）修改维修工单状态，例如 待处理 → 处理中 → 已完成。"""
    ctx = runtime.context
    t = ticket_service.update_status(ticket_id, new_status, ctx.user_id, ctx.role, note)
    return f"工单 {t['ticket_id']} 状态已更新为「{t['status']}」。"
