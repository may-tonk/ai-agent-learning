"""
组装 agent，并提供「一段会话」的运行接口

【Agents 模块的核心：create_agent】
create_agent 内部用 LangGraph 搭好了一张图：
    model 节点（调用模型）⇄ tools 节点（执行工具），模型不再请求工具时结束
我们传进去的每个参数，都是在给这张图配零件：
    model           大脑：用哪个模型
    tools           手：能调用哪些工具
    middleware      在循环的各个位置插入的逻辑（提示词、权限、日志、限流、审批…）
    state_schema    State 里除了 messages 还有哪些字段
    context_schema  invoke 时传入的 context 是什么结构
    checkpointer    把每个 thread_id 的 State 存起来，实现多轮记忆和「暂停后继续」

【在整体流程里的位置】
    main.py 启动时调用 build_agent() 一次 → 得到 agent（整个程序共用）
    main.py 登录后创建 CustomerServiceSession(agent, context) → 每个问题调用 session.ask(text)
    session.ask → agent.stream → 中间件 / 模型 / 工具 → 产生事件 → main.py 的 render 打印
"""
import uuid
from collections.abc import Iterator

from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    SummarizationMiddleware,
    ToolCallLimitMiddleware,
)
from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent.middleware import build_system_prompt, filter_tools_by_role, guard_tool_call, track_token_usage
from agent.state import CustomerServiceState, UserContext
from agent.tools import ALL_TOOLS
from model.factory import build_chat_model, get_chat_model
from utils.config_handler import agent_conf


def build_agent(model: BaseChatModel | None = None, checkpointer=None, use_backup_models: bool = True):
    """
    model：默认用 config/model.yml 的主模型；测试时传入假模型，不花钱、结果固定
    checkpointer：默认 InMemorySaver（存在内存里，程序退出就没了）；正式项目换成 PostgresSaver
    use_backup_models：是否启用「备用模型」和「对话摘要」这两个需要额外调用真实模型的中间件
                       （tests/ 和 lessons/03 用假模型时传 False，避免去创建真实模型）
    返回：编译好的 agent（LangGraph 的 CompiledStateGraph），有 invoke / stream / get_state 等方法
    谁调用：main.py 的 main()、lessons/03、lessons/04、tests/test_agent_flow.py

    【middleware 列表的顺序有讲究】
    模型调用前的钩子按列表顺序执行，模型调用后的钩子按相反顺序执行（像洋葱一层层包住模型调用）。
    """
    middleware = []

    if use_backup_models:
        middleware += [
            # 对话 token 超过阈值时，把旧消息交给摘要模型压缩成一段摘要，只保留最近 N 条原文
            # 解决的问题：多轮对话越来越长，每次调用模型都要把全部历史重新发一遍，token 成本越来越高
            # 参数：
            #   model    做摘要用的模型（config/model.yml 的 summary 段，temperature=0）
            #   trigger  什么时候触发：("tokens", 6000) = 历史消息超过 6000 token 时
            #            也可以写 ("messages", 50) = 超过 50 条消息时
            #   keep     压缩后保留多少原文：("messages", 12) = 保留最近 12 条不压缩
            #   这两个数字在 config/agent.yml 里调（summary_trigger_tokens / summary_keep_messages）
            SummarizationMiddleware(
                model=build_chat_model("summary"),
                trigger=("tokens", agent_conf["summary_trigger_tokens"]),
                keep=("messages", agent_conf["summary_keep_messages"]),
            ),
            # 主模型调用失败（重试后仍失败）时，自动换备用模型再试一次
            # 参数：备用模型，可以传多个，按顺序逐个尝试（config/model.yml 的 fallback 段）
            ModelFallbackMiddleware(build_chat_model("fallback")),
        ]

    middleware += [
        # 一轮提问里模型最多被调用几次，到了就结束这一轮（防止死循环烧钱）
        # 参数：
        #   run_limit      每一轮（一次 invoke / stream）的上限，config/agent.yml 的 model_call_run_limit
        #                  （还有 thread_limit：整段对话的总上限，这里没用）
        #   exit_behavior  到上限后怎么办："end" = 结束这一轮，最后一条消息是提示「超过上限」
        #                  （另一个选项 "error" = 直接抛异常）
        ModelCallLimitMiddleware(run_limit=agent_conf["model_call_run_limit"], exit_behavior="end"),
        # 一轮里工具最多调用几次，超了就告诉模型「不能再调了」
        # 参数：
        #   run_limit      config/agent.yml 的 tool_call_run_limit
        #   exit_behavior  "continue" = 拦下多出来的工具调用，返回错误消息给模型，让模型用已有信息回答
        #                  （"end" = 直接结束这一轮；"error" = 抛异常）
        ToolCallLimitMiddleware(run_limit=agent_conf["tool_call_run_limit"], exit_behavior="continue"),
        # 下面四个是我们自己写的（agent/middleware.py）
        build_system_prompt,
        filter_tools_by_role,
        track_token_usage,
        guard_tool_call,
        # 会写数据的工具，执行前暂停等人工审批。批准 / 拒绝两种选择
        # 参数：
        #   interrupt_on  {工具名: 配置}：哪些工具要审批。allowed_decisions 是客服可以做的决定：
        #                   "approve" 批准（按原参数执行）、"reject" 拒绝（不执行，理由回给模型）
        #                   还可以加 "edit"（客服修改参数后再执行），这里没开放
        #   description_prefix  审批请求里的说明文字前缀
        # 原理：模型决定调用这些工具后，agent 在执行前 interrupt（暂停），State 存进 checkpointer；
        #       之后用 Command(resume={"decisions": [...]}) 继续，见下面的 resume()
        #       所以审批必须配合 checkpointer 使用
        HumanInTheLoopMiddleware(
            interrupt_on={
                name: {"allowed_decisions": ["approve", "reject"]}
                for name in agent_conf["approval_required_tools"]
            },
            description_prefix="以下操作需要客服审批",
        ),
    ]

    # create_agent 参数含义见文件开头
    return create_agent(
        model=model or get_chat_model(),
        tools=ALL_TOOLS,
        middleware=middleware,
        state_schema=CustomerServiceState,
        context_schema=UserContext,
        # InMemorySaver：每走一步就把 State 存一个「检查点」到内存，按 thread_id 区分不同对话
        checkpointer=checkpointer or InMemorySaver(),
    )


class CustomerServiceSession:
    """
    一个用户的一段客服会话。

    把 agent 的原始输出（各种消息、中断）整理成简单的事件，交给界面层（main.py）显示：
        ("token", 文本片段)            模型正在生成的回答，逐段到达
        ("tool_call", 名字, 参数)      模型决定调用工具
        ("tool_result", 名字, 内容, artifact)
        ("approval", [待审批的操作])   遇到需要人工审批的工具，agent 已暂停
        ("final", 文本)                return_direct 工具直接给出的最终回答
    界面层不需要知道 LangGraph 的数据结构；以后换成网页（FastAPI / Streamlit）也只改界面层。
    """

    def __init__(self, agent, context: UserContext):
        """
        agent：build_agent() 的返回值（多个会话可以共用一个 agent）
        context：当前登录用户，之后每次调用 agent 都会带上
        """
        self.agent = agent
        self.context = context
        self.new_thread()

    def new_thread(self) -> str:
        """
        开一段新对话：换一个新的 thread_id，之前的消息不会再带入（main.py 的 /new 命令）。
        返回：新的 thread_id，格式为 <user_id>-<8 位随机串>，例如 U1001-26bb34ba
        """
        # thread_id 是 checkpointer 找存档用的钥匙：同一个 thread_id → 同一段对话历史
        self.thread_id = f"{self.context.user_id}-{uuid.uuid4().hex[:8]}"
        # config 是 LangGraph 的运行配置，thread_id 必须放在 "configurable" 里
        self.config = {"configurable": {"thread_id": self.thread_id}}
        self._seen_call_ids: set[str] = set()
        return self.thread_id

    def ask(self, text: str) -> Iterator[tuple]:
        """
        用户发一句话
        text：用户输入
        返回：事件生成器（见类说明）；只发新消息就够了，历史消息由 checkpointer 自动加载
        """
        yield from self._run({"messages": [HumanMessage(text)]})

    def resume(self, approved: bool, reason: str = "") -> Iterator[tuple]:
        """
        客服审批后，让暂停的 agent 继续。Command(resume=...) 的内容会交给 HumanInTheLoopMiddleware
        approved：True 批准 / False 拒绝
        reason：拒绝理由，会作为 ToolMessage 交给模型，模型据此回复用户
        返回：继续运行产生的事件生成器
        注意：一次可能有多个待审批操作（模型同时请求了多个工具），这里对它们做同样的决定，
              decisions 列表的顺序和数量必须和待审批操作一一对应
        """
        pending = self.pending_approvals()
        if approved:
            decisions = [{"type": "approve"} for _ in pending]
        else:
            decisions = [{"type": "reject", "message": reason or "客服审核未通过"} for _ in pending]
        # Command(resume=...)：从上次 interrupt 的地方继续执行，resume 的值就是 interrupt 的「返回值」
        yield from self._run(Command(resume={"decisions": decisions}))

    def pending_approvals(self) -> list[dict]:
        """
        当前是否停在审批上，停在哪些操作上
        返回：待审批操作列表，每项形如 {"name": 工具名, "args": 参数, ...}；没有暂停时是空列表
        """
        # get_state：从 checkpointer 读这个 thread 的最新快照；snapshot.tasks 里带着未处理的 interrupt
        snapshot = self.agent.get_state(self.config)
        requests = []
        for task in snapshot.tasks:
            for intr in task.interrupts:
                requests.extend(intr.value.get("action_requests", []))
        return requests

    def state(self) -> dict:
        """checkpointer 里保存的这段对话的 State（messages、current_order_id、token_usage）"""
        return self.agent.get_state(self.config).values

    def _run(self, payload) -> Iterator[tuple]:
        """
        真正运行 agent，并把 LangGraph 的输出翻译成事件。
        payload：新的输入 {"messages": [...]}，或审批后继续用的 Command(resume=...)
        """
        # agent.stream 的参数：
        #   payload      输入
        #   config       带 thread_id，决定读写哪段对话的存档
        #   context      UserContext，工具和中间件通过 runtime.context 读取
        #   stream_mode  要哪几种流式数据（lessons/04 第 2 节对比了三种：values / updates / messages）
        # stream_mode 同时要两种数据：
        #   "messages" → 模型生成回答时的一个个 AIMessageChunk（实现打字机效果）
        #   "updates"  → 每个节点执行完后对 State 的更新（工具调用、工具结果、中断）
        # 传了多个 mode 时，每次产出的是 (mode, data) 二元组
        for mode, data in self.agent.stream(
            payload,
            config=self.config,
            context=self.context,
            stream_mode=["messages", "updates"],
        ):
            if mode == "messages":
                # data = (消息片段, 元数据)；元数据里的 langgraph_node 表示是哪个节点产生的
                chunk, meta = data
                # 只要 model 节点产生的文本；摘要中间件内部调用模型时产生的片段不显示
                # 模型支持流式时这里是一段段 AIMessageChunk；不支持流式时是一整条 AIMessage
                if meta.get("langgraph_node") == "model" and isinstance(chunk, AIMessage) and chunk.text:
                    yield ("token", chunk.text)
                continue

            # mode == "updates"：data 形如 {节点名: 该节点返回的更新}
            for node, update in data.items():
                if node == "__interrupt__":
                    # 审批中断：agent 已暂停，等 resume
                    for intr in update:
                        yield ("approval", intr.value.get("action_requests", []))
                    continue
                if not isinstance(update, dict):
                    continue
                for msg in update.get("messages", []) or []:
                    if isinstance(msg, AIMessage):
                        for call in msg.tool_calls:
                            # 审批中断恢复后，同一条 AIMessage 会再出现一次，用调用 ID 去重
                            if call["id"] in self._seen_call_ids:
                                continue
                            self._seen_call_ids.add(call["id"])
                            yield ("tool_call", call["name"], call["args"])
                    elif isinstance(msg, ToolMessage):
                        # artifact：search_knowledge 的来源文件和距离，main.py 用来显示「参考资料」
                        yield ("tool_result", msg.name, msg.content, msg.artifact)

        # return_direct 的工具结果直接作为最终回答：最后一条消息是 ToolMessage
        messages = self.state().get("messages", [])
        if messages and isinstance(messages[-1], ToolMessage) and not self.pending_approvals():
            yield ("final", messages[-1].content)
