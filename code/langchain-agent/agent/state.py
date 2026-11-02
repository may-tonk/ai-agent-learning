"""
State 和 Context：agent 运行时的两类数据

【State（状态）】这一段对话「当前的情况」，会变：
    - messages：AgentState 自带，整段对话的消息列表
    - current_order_id：我们加的字段，用户正在咨询哪个订单（工具查订单时用 Command 写进来）
    - token_usage：我们加的字段，这段对话累计用了多少 token（中间件每次调用模型后累加）
    State 会被 checkpointer 按 thread_id 保存，下一轮提问还能读到。

【Context（上下文）】这一次调用「是谁在用」，由程序在 invoke 时传入，整轮不变，模型改不了：
    - user_id、role：登录信息。工具从 runtime.context 读，而不是让模型当参数填，
      否则用户说一句「帮我查 U1002 的订单」，模型就可能照做。

【在整体流程里的位置】
    定义在这里 → agent/agent.py 的 create_agent(state_schema=..., context_schema=...) 登记
    main.py 登录时创建 UserContext → 每次 agent.stream(..., context=...) 传入
    读的地方：工具里的 runtime.context / runtime.state，中间件里的 request.runtime.context / request.state
    写 State 的地方：工具返回 Command(update=...)，中间件返回 {"字段": 新值}
"""
from dataclasses import dataclass

from langchain.agents import AgentState
from typing_extensions import NotRequired


class CustomerServiceState(AgentState):
    """
    继承 AgentState（自带 messages 字段，并用 add_messages 规则「追加」新消息，而不是覆盖）。
    这里新增的字段用的是「直接覆盖」规则：谁返回新值，就用新值替换旧值。
    """

    # NotRequired：刚开始对话时还没有这个字段，第一次查订单后才会被写入
    # 写入方：agent/tools/order_tools.py 的 get_order_detail（返回 Command）
    # 读取方：agent/middleware.py 的 build_system_prompt，填进系统提示词「正在处理的订单」
    current_order_id: NotRequired[str]
    # {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "model_calls": 0}
    # 写入方：agent/middleware.py 的 track_token_usage；main.py 的 /state 命令可以查看
    token_usage: NotRequired[dict]


@dataclass
class UserContext:
    """
    当前登录用户。main.py 的 choose_user 创建，整个会话不变。
    为什么用 dataclass 而不是放进 State：Context 是「只读的运行参数」，不需要被 checkpointer 保存，也不允许被修改。
    """

    user_id: str     # 如 U1001；所有 services 的权限检查都靠它
    user_name: str   # 如 张三；只用于系统提示词里称呼用户
    role: str  # customer = 普通用户；supervisor = 客服主管
