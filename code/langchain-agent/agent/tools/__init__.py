"""
所有工具在这里汇总。agent.py 只从这里取，新增工具时只改这个文件和 config/agent.yml 的 role_tools。

【新增一个工具的步骤】
1. 在 agent/schemas.py 写参数类（可选，参数简单时可以直接用函数签名）
2. 在 agent/tools/xxx_tools.py 用 @tool 写函数，docstring 写清楚「做什么、什么时候调用」
3. 加到下面的 ALL_TOOLS
4. 在 config/agent.yml 的 role_tools 里给能用它的角色登记（否则 filter_tools_by_role 会把它过滤掉）
5. 如果它会写数据，再加到 approval_required_tools
"""
from agent.tools.kb_tools import search_knowledge
from agent.tools.order_tools import check_warranty, get_order_detail, list_my_orders
from agent.tools.ticket_tools import create_repair_ticket, get_ticket_status, update_ticket_status

# 传给 create_agent(tools=ALL_TOOLS) 的全部工具；每次调用模型前再按角色筛一遍
ALL_TOOLS = [
    search_knowledge,
    list_my_orders,
    get_order_detail,
    check_warranty,
    create_repair_ticket,
    get_ticket_status,
    update_ticket_status,
]
