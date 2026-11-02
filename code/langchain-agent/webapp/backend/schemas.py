"""
【v2 网页版新增】接口的请求 / 响应格式（Pydantic 模型）

【为什么要单独定义】这是前后端之间的「合同」：
    请求模型（ChatRequest）：FastAPI 收到 JSON 后自动按它校验，不合格直接返回 422，路由函数里不用再写 if 判断
    响应模型（ChatResponse）：规定返回给前端哪些字段，多余的字段（比如 State 里的内部数据）不会被带出去
FastAPI 还会根据这些类自动生成接口文档：后端启动后打开 http://127.0.0.1:8001/docs 就能看到、能直接试调用。

和 agent/schemas.py 的区别：
    agent/schemas.py      是给「模型」看的（工具参数、结构化输出），description 会发给模型
    webapp/backend/schemas.py 是给「前端」看的（HTTP 接口），和模型无关

谁用它：routers/chat.py、routers/users.py
"""
from pydantic import BaseModel, Field

from agent.schemas import ServiceSummary

# thread_id 格式：<user_id>-<8 位十六进制>，例如 U1001-26bb34ba（和命令行版 CustomerServiceSession.new_thread 一样）
# 用正则卡住格式：防止前端传进来乱七八糟的字符串，直接在校验阶段就拦下
THREAD_ID_PATTERN = r"^[A-Za-z0-9]+-[0-9a-f]{8}$"


class ChatRequest(BaseModel):
    """POST /api/chat 的请求体"""

    # 不传（null）= 开始新对话，后端生成一个新的 thread_id 并在响应里返回；
    # 传了 = 接着这段对话聊，后端用它从 checkpointer 读出历史
    thread_id: str | None = Field(default=None, pattern=THREAD_ID_PATTERN, description="会话 ID；新对话不传")
    # 长度限制：空消息没意义；太长的输入既费 token，也可能是有人在刷接口
    message: str = Field(min_length=1, max_length=2000, description="用户这次说的话")


class ResumeRequest(BaseModel):
    """【阶段 3】POST /api/chat/resume 的请求体：对停在审批上的对话做决定"""

    # 必填：审批一定是针对某段已经存在的对话
    thread_id: str = Field(pattern=THREAD_ID_PATTERN, description="停在审批上的会话 ID")
    approved: bool = Field(description="true 批准（执行工具）/ false 拒绝（不执行）")
    # 拒绝理由会作为工具结果交给模型，模型据此回复用户；限制长度，理由同 ChatRequest.message
    reason: str = Field(default="", max_length=200, description="拒绝理由，可不填")


class ToolCallInfo(BaseModel):
    """一次工具调用（或一个待审批的操作）：名字 + 参数"""

    name: str
    args: dict


class ChatResponse(BaseModel):
    """POST /api/chat 的响应体"""

    thread_id: str = Field(description="这段对话的 ID；前端要保存起来，下一句话带上")
    answer: str = Field(description="客服这一轮的回答；停在审批上时可能为空")
    # default_factory=list：没有时是空列表（不能写 default=[]，原因见 agent/schemas.py 的说明）
    tool_calls: list[ToolCallInfo] = Field(default_factory=list, description="这一轮模型调用了哪些工具")
    sources: list[str] = Field(default_factory=list, description="知识库参考资料的文件名（来自 search_knowledge 的 artifact）")
    pending_approvals: list[ToolCallInfo] = Field(
        default_factory=list, description="等待审批的操作；不为空说明 agent 停在审批上，要调 POST /api/chat/resume 批准或拒绝"
    )
    token_usage: dict | None = Field(default=None, description="这段对话累计 token（来自 State 的 token_usage）")


class ThreadInfo(BaseModel):
    """【阶段 4】GET /api/threads 返回的一个会话（左侧会话列表的一行）"""

    thread_id: str
    title: str = Field(description="第一句话的前 30 个字")
    created_at: str
    updated_at: str = Field(description="最后一次对话的时间，列表按它倒序")


class HistoryMessage(BaseModel):
    """
    【阶段 4】GET /api/threads/{id}/messages 返回的一条历史消息，形状和前端 MessageBubble 的 message 一致。
    用户消息只有 text，其余字段用默认值补上；客服消息的字段由 streaming/recorder.py 整理
    """

    id: int
    role: str = Field(description="user / assistant")
    text: str = ""
    tools: list[dict] = Field(default_factory=list, description="[{id, name, args, status, progress（阶段 6）}]")
    sources: list[str] = Field(default_factory=list)
    pending: list[ToolCallInfo] = Field(default_factory=list, description="还在等审批的操作：刷新后审批卡片照样显示")
    decision: dict | None = Field(default=None, description="审批记录 {approved, reason, items}")
    stopped: bool = False
    error: str | None = None


class ThreadState(BaseModel):
    """【阶段 4】GET /api/threads/{id}/state：checkpointer 存档里这段对话的 State（侧边栏「当前会话」卡片显示）"""

    thread_id: str
    current_order_id: str | None = Field(default=None, description="正在咨询的订单（工具查订单时写进 State）")
    token_usage: dict | None = None
    memory_messages: int = Field(description="存档里的消息条数 = 下次调用模型时带上的历史；对话很长被摘要压缩后会变少")


class SummaryResponse(BaseModel):
    """【阶段 5】GET / POST /api/threads/{id}/summary：会话小结（页面顶部的小结卡片显示）"""

    # 直接复用 agent/schemas.py 的 ServiceSummary：模型输出、数据库、接口三处用同一个类，字段改一处就都改了
    summary: ServiceSummary
    created_at: str
    message_count: int = Field(description="生成时这段对话有几条消息")
    stale: bool = Field(description="生成之后又有了新消息：小结只代表之前的对话，页面提示「已过期，可以重新生成」")


class ChainToolCall(BaseModel):
    """【阶段 5】AIMessage 里的一个工具调用请求"""

    id: str
    name: str
    args: dict


class ChainMessage(BaseModel):
    """
    【阶段 5】GET /api/threads/{id}/chain 的一项：checkpointer 存档里的一条原始消息（「消息链」调试面板显示）
    看点：AIMessage 的 tool_calls[].id 和后面 ToolMessage 的 tool_call_id 一一对应 —— 模型就是靠这个 ID 知道哪个结果回答哪个请求
    """

    index: int = Field(description="在 State.messages 里的位置，从 0 开始")
    type: str = Field(description="human / ai / tool / system，和 LangChain 消息类的 type 属性一致")
    text: str = Field(description="文字内容，超过 300 字截断")
    length: int = Field(description="原文一共多少字（截断了就能看出来）")
    tool_calls: list[ChainToolCall] = Field(default_factory=list, description="只有 ai 消息有：这次请求调用的工具")
    tool_call_id: str | None = Field(default=None, description="只有 tool 消息有：回答的是哪个工具调用")
    tool_name: str | None = None
    status: str | None = Field(default=None, description="tool 消息的 status：success / error")
    is_summary: bool = Field(default=False, description="是 SummarizationMiddleware 压缩出来的摘要，不是用户说的话")


class UserInfo(BaseModel):
    """GET /api/users 返回的一个用户。只给登录下拉框需要的字段，手机号这种隐私字段不返回"""

    user_id: str
    name: str
    role: str
