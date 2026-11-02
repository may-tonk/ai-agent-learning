"""
Pydantic 数据结构：工具参数 + 结构化输出

【Tools 模块】@tool(args_schema=XxxInput) 时，LangChain 会把这里的类转换成 JSON Schema 发给模型，
模型照着它填参数；模型填完后，执行工具前 Pydantic 再按同一套规则校验一遍，不合格直接拦下。
所以这里的约束有两个作用：
1. 告诉模型「参数长什么样」（description 会出现在发给模型的 schema 里）
2. 在代码层面拦住不合格的参数（模型生成的参数是不可信输入）

【Models / Agents 模块】ServiceSummary 是结构化输出的格式：
要求模型按固定字段返回，而不是一段自由文本，方便程序存库、统计。

【Field 常用参数速查】
    description    参数说明，会原样发给模型 —— 这是「写给模型看的文档」，写清楚格式和例子，模型填得更准
    pattern        正则约束（字符串必须匹配）
    min_length / max_length  字符串长度范围
    default / default_factory  默认值；有默认值的字段模型可以不填（不在 required 里）
    Literal[...]   只能取这几个值之一，在 schema 里变成 enum
想看模型实际收到的 schema：lessons/03_tools.py 第 1 节会打印出来，或者 print(XxxInput.model_json_schema())

【谁用它】
    工具参数类 → agent/tools/*.py 的 @tool(args_schema=...)
    ServiceSummary → services/summary_service.py 的 with_structured_output
    DeviceWarrantyReport → lessons/04_agents.py 第 6 节的 create_agent(response_format=...)
"""
from typing import Literal

from pydantic import BaseModel, Field

# 订单号格式：SO + 8 位数字。用正则限制，模型把「我的订单」「第二个」这种话直接塞进来会被拦下
ORDER_ID_PATTERN = r"^SO\d{8}$"
# 工单号格式：TK + 12 位数字（8 位日期 + 4 位序号，见 services/ticket_service._new_ticket_id）
TICKET_ID_PATTERN = r"^TK\d{12}$"

# 故障类型只能从这几种里选。Literal 会变成 JSON Schema 里的 enum，模型只能在其中挑
# 为什么不让模型随便写：后面要按故障类型查「对应哪个部件、保修几个月」，自由文本没法匹配规则
# 新增故障类型时：这里加一项，同时在 data/warranty_rules.json 的 fault_to_part 里登记对应部件
FaultCategory = Literal[
    "无法开机或充电",
    "续航明显变短",
    "导航迷路或建图异常",
    "吸力下降",
    "噪音异常",
    "拖地漏水",
    "滚刷边刷损坏",
    "其他",
]

# 工单状态；能怎么流转由 services/ticket_service.py 的 ALLOWED_TRANSITIONS 决定
TicketStatus = Literal["待处理", "处理中", "已完成", "已关闭"]


# ---------------- 工具参数 ----------------
# 注意：这些类的说明用 # 注释写在类上方，而不是写成 docstring ——
# Pydantic 类的 docstring 会变成 JSON Schema 的 description 一起发给模型，改它等于改了模型看到的内容

# search_knowledge 的参数
class SearchKnowledgeInput(BaseModel):
    # 长度限制：太短（1 个字）检索不出东西，太长说明模型把整段对话塞进来了
    query: str = Field(
        min_length=2,
        max_length=100,
        description="用于检索产品知识库的问题，尽量改写成包含关键词的完整问句，例如「扫地机器人 迷路 重新建图 方法」",
    )


# get_order_detail 的参数
class OrderIdInput(BaseModel):
    order_id: str = Field(
        pattern=ORDER_ID_PATTERN,
        description="订单号，格式为 SO 加 8 位数字，例如 SO20260312。不知道订单号时先调用 list_my_orders",
    )


# check_warranty 的参数
class CheckWarrantyInput(BaseModel):
    order_id: str = Field(pattern=ORDER_ID_PATTERN, description="订单号，格式为 SO 加 8 位数字")
    fault_category: FaultCategory = Field(description="故障类型，必须从给定选项中选择最接近的一项")


# create_repair_ticket 的参数（这个工具执行前需要人工审批）
class CreateTicketInput(BaseModel):
    order_id: str = Field(pattern=ORDER_ID_PATTERN, description="出故障的机器对应的订单号")
    fault_category: FaultCategory = Field(description="故障类型，必须从给定选项中选择最接近的一项")
    # 至少 5 个字：防止模型只写「坏了」这种对维修人员没用的描述
    description: str = Field(
        min_length=5,
        max_length=300,
        description="用用户的原话概括故障现象：什么时候开始、具体表现、已经尝试过哪些处理",
    )
    # 有默认值 → 模型可以不填；description 里写清楚判断标准，模型才知道什么时候选加急
    urgency: Literal["普通", "加急"] = Field(
        default="普通",
        description="完全无法使用（无法开机、漏水）选加急，其余选普通",
    )


# get_ticket_status 的参数
class TicketIdInput(BaseModel):
    ticket_id: str = Field(pattern=TICKET_ID_PATTERN, description="工单号，格式为 TK 加 12 位数字")


# update_ticket_status 的参数（仅客服主管可见，执行前需要人工审批）
class UpdateTicketInput(BaseModel):
    ticket_id: str = Field(pattern=TICKET_ID_PATTERN, description="工单号")
    new_status: TicketStatus = Field(description="工单的新状态")
    note: str = Field(default="", max_length=200, description="处理备注，例如维修结果")


# ---------------- 结构化输出 ----------------
# 这里类和字段的 description 会发给模型，相当于「填表说明」

class ServiceSummary(BaseModel):
    """一次客服会话结束后的服务小结（客服系统里每通对话都要留档）"""

    user_intent: str = Field(description="用户这次来的主要诉求，一句话")
    category: Literal["产品使用咨询", "故障报修", "订单物流", "保修政策", "投诉建议", "其他"] = Field(
        description="会话分类"
    )
    # default_factory=list：每次新建一个空列表作为默认值（不能写 default=[]，那样所有对象会共用同一个列表）
    related_orders: list[str] = Field(default_factory=list, description="涉及的订单号，没有就是空列表")
    ticket_ids: list[str] = Field(default_factory=list, description="本次创建或查询的工单号")
    resolved: bool = Field(description="用户的问题在本次对话中是否已经解决")
    satisfaction_risk: Literal["低", "中", "高"] = Field(
        description="用户不满意的风险：语气激动、反复追问、提到投诉时为高"
    )
    follow_up: str = Field(description="后续需要人工跟进的事项，没有就写「无」")


# DeviceWarrantyReport 里的一台设备
class DeviceWarranty(BaseModel):
    order_id: str = Field(description="订单号")
    product: str = Field(description="产品名称")
    in_warranty: bool = Field(description="主机是否在保修期内，以 check_warranty 工具结果为准")
    expire_date: str = Field(description="主机保修截止日期，YYYY-MM-DD")


class DeviceWarrantyReport(BaseModel):
    """「我的设备」页面用的数据：前端要的是固定字段，不是一段话"""

    # 列表里套 Pydantic 类：模型要返回一个对象数组，每个对象都按 DeviceWarranty 的字段填
    devices: list[DeviceWarranty] = Field(description="当前用户名下每台已签收设备的保修情况")
    advice: str = Field(description="给用户的一句话提醒，例如哪台快过保了")
