"""
自定义中间件：在 agent 循环的固定位置插入我们自己的逻辑

agent 一轮的执行顺序（简化）：
    用户消息 → [模型调用前] → 调用模型 → [模型调用后] → 有工具调用？ → [工具调用前后] → 执行工具 → 回到模型 …

LangChain 给这些位置都留了「钩子」，用装饰器把普通函数挂上去：
    @dynamic_prompt   每次调用模型前，现场生成系统提示词
    @wrap_model_call  把「调用模型」这一步包起来：可以改请求（比如换掉工具列表），再交给 handler 真正调用
    @after_model      模型返回后执行：可以读结果、更新 State
    @wrap_tool_call   把「执行工具」这一步包起来：记录日志、计时、捕获异常

这些函数自己不会被调用，是 create_agent(middleware=[...]) 登记后，由 agent 运行时在对应位置调用。

【在整体流程里的位置】agent/agent.py 的 build_agent 把这 4 个函数放进 middleware 列表。
每一次「调用模型」都会经过 build_system_prompt、filter_tools_by_role、track_token_usage，
每一次「执行工具」都会经过 guard_tool_call。一轮提问里它们可能各被调用好几次。

【两个常见参数】
    request.runtime.context  invoke 时传入的 UserContext（是谁在用）
    request.state            当前 State（messages、current_order_id、token_usage）
    handler                  「下一步」：调用它才会真正执行模型 / 工具；不调用就等于拦截

【v2 网页版】同步和异步：
    命令行版用 agent.stream（同步），网页后端用 agent.astream_events / ainvoke（异步）。
    异步运行时，框架调用的是中间件的「异步版本」（awrap_model_call、awrap_tool_call），
    所以 2、4 两个从「装饰器函数」改成了「类」，同时写了同步和异步两个方法，规则只写一份（见各自的说明）。
    1、3 不用改：@dynamic_prompt、@after_model 装饰同步函数时，框架会自动生成异步版本。
"""
import time
from collections.abc import Awaitable, Callable
from datetime import date

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    after_model,
    dynamic_prompt,
)
from langchain.messages import AIMessage, ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from agent.state import CustomerServiceState, UserContext
from services.errors import BusinessError
from utils.config_handler import agent_conf
from utils.logger_handler import logger
from utils.prompt_loader import load_prompt


# ---------------------------------------------------------------------------
# 1. 动态系统提示词：把「当前是谁、今天几号、正在处理哪个订单」填进提示词模板
# ---------------------------------------------------------------------------
@dynamic_prompt
def build_system_prompt(request: ModelRequest) -> str:
    """
    每次调用模型前执行，返回值就是这次调用的系统提示词（SystemMessage）。
    request：本次模型调用的请求（包含 messages、tools、runtime、state）
    返回：填好占位符的提示词字符串（模板在 prompts/system_prompt.txt）
    为什么是「动态」的：日期每天变、current_order_id 每次查订单后会变，写死在提示词里就过时了
    注意：系统提示词 + 工具 schema 每次调用都会发送，约占 1500 token，提示词越长每次越贵
    """
    # request.runtime.context：invoke 时传进来的 UserContext
    # request.state：当前 State（包括工具用 Command 写进去的 current_order_id）
    ctx: UserContext = request.runtime.context
    return load_prompt("system").format(
        user_name=ctx.user_name,
        role="客服主管" if ctx.role == "supervisor" else "普通用户",
        # 日期由程序提供：模型自己不知道今天几号，判断「最近」「过保」时会用到
        today=date.today().isoformat(),
        current_order_id=request.state.get("current_order_id") or "暂无",
    )


# ---------------------------------------------------------------------------
# 2. 按角色筛选工具：普通用户的这次模型调用里，根本看不到 update_ticket_status
# ---------------------------------------------------------------------------
# 【v2 网页版】原来是 @wrap_model_call 装饰的一个同步函数，现在改成类。原因（看过 langchain 1.4.6 源码
#   agents/middleware/types.py，并在 lessons/05 第 6 节实测报错）：
#   @wrap_model_call 装饰同步函数时，只生成同步方法 wrap_model_call；
#   网页后端异步运行时，框架要调用 awrap_model_call，找不到就报
#   NotImplementedError: Asynchronous implementation of awrap_model_call is not available
# 真实项目的做法：写成 AgentMiddleware 的子类，同步、异步两个方法都实现，「过滤规则」抽成普通函数共用，
#   这样命令行（同步）和网页（异步）走的是同一份规则，以后改规则只改 _visible_tools 一处。
def _visible_tools(request: ModelRequest) -> list:
    """
    按 config/agent.yml 的 role_tools，算出这个角色能看到的工具。
    request.tools：create_agent 登记的全部工具（ALL_TOOLS）
    返回：过滤后的工具列表
    """
    role = request.runtime.context.role
    # 配置里没有这个角色 → 空集合 → 模型一个工具都看不到（安全的默认值）
    allowed = set(agent_conf["role_tools"].get(role, []))
    return [t for t in request.tools if t.name in allowed]


class RoleToolFilter(AgentMiddleware):
    """
    每次调用模型前，按角色过滤工具列表，再交给 handler 真正调用模型。
    好处：模型看不到的工具既不会被误调用，也不占 token（每个工具的 schema 都要发给模型）
    继承 AgentMiddleware：框架规定的中间件基类，子类实现哪个钩子方法，就在哪个位置被调用
    """

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """
        同步版：命令行 main.py（agent.stream）走这里。
        handler：真正调用模型的函数；返回：模型的响应（原样返回，不做修改）
        """
        # override：复制一份请求，只替换 tools，原请求不变
        return handler(request.override(tools=_visible_tools(request)))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """
        异步版：网页后端（agent.ainvoke / astream_events）走这里。
        和同步版唯一的区别：handler 是异步函数，要 await 它
        """
        return await handler(request.override(tools=_visible_tools(request)))


# 创建一个实例，名字和原来的函数一样：agent/agent.py 的 middleware 列表、import 语句都不用改
filter_tools_by_role = RoleToolFilter()


# ---------------------------------------------------------------------------
# 3. 每次调用模型后：记录 token 用量，并累加进 State
# ---------------------------------------------------------------------------
@after_model(state_schema=CustomerServiceState)
def track_token_usage(state: CustomerServiceState, runtime: Runtime[UserContext]) -> dict | None:
    """
    模型每返回一次就执行一次：读最后一条 AIMessage 的 usage_metadata，累加到 State 的 token_usage。
    state_schema=CustomerServiceState：告诉框架这个中间件会读写我们自定义的 token_usage 字段
    state：当前 State（此时最后一条消息就是模型刚返回的 AIMessage）
    runtime：运行时信息（这里没用到 context，但签名要求有）
    返回：要合并进 State 的字典；返回 None 表示不更新
    日志示例：[模型调用] 输入 1513 / 输出 66 token｜请求工具 ['search_knowledge']｜本对话累计 1579 token，1 次调用
    """
    last = state["messages"][-1]
    # 有的模型 / 假模型不返回 usage_metadata，没有就跳过
    if not isinstance(last, AIMessage) or not last.usage_metadata:
        return None

    usage = last.usage_metadata  # {"input_tokens": .., "output_tokens": .., "total_tokens": .., ...}
    # dict(...) 复制一份再改：不直接修改 State 里的旧对象
    total = dict(state.get("token_usage") or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "model_calls": 0})
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        total[key] += usage.get(key, 0)
    total["model_calls"] += 1

    tool_names = [c["name"] for c in last.tool_calls]
    logger.info(
        f"[模型调用] 输入 {usage.get('input_tokens')} / 输出 {usage.get('output_tokens')} token"
        f"｜{'请求工具 ' + str(tool_names) if tool_names else '给出回答'}"
        f"｜本对话累计 {total['total_tokens']} token，{total['model_calls']} 次调用"
    )
    # 返回的字典会合并进 State（这里只更新 token_usage 这一个字段）
    return {"token_usage": total}


# ---------------------------------------------------------------------------
# 4. 工具执行守卫：日志 + 计时 + 把异常变成模型能看懂的错误消息
# ---------------------------------------------------------------------------
# 【v2 网页版】原来是 @wrap_tool_call 装饰的函数，现在改成类，原因和第 2 节一样：
#   @wrap_tool_call 装饰同步函数时只生成同步方法 wrap_tool_call，网页后端异步运行时要找 awrap_tool_call，
#   找不到就报 NotImplementedError。
# 共用部分抽成两个普通函数：_tool_error_message（异常 → 错误消息）、_log_done（记录用时），
#   同步版和异步版只差「handler 要不要 await」这一行。
def _tool_error_message(call: dict, e: Exception) -> ToolMessage:
    """
    把工具执行时抛出的异常，变成一条模型能看懂的错误 ToolMessage。
    call：模型请求的这次调用 {"name", "args", "id"}
    e：捕获到的异常
    返回：status="error" 的 ToolMessage（tool_call_id 对应这次调用）
    为什么必须返回 ToolMessage 而不是让异常抛出去：
        ① 不捕获的话整轮对话直接崩溃，用户什么都收不到
        ② 模型请求了工具就必须收到一条 tool_call_id 对应的 ToolMessage，否则下次调用模型会报 400
    """
    if isinstance(e, BusinessError):
        # 业务异常（没权限、不存在、违反规则）：属于「正常的失败」，把原因交给模型，由它转告用户
        # 这段文字也可能直接显示给用户（return_direct 的工具），所以写成用户能看懂的话
        logger.warning(f"[工具调用] {call['name']} 业务拒绝：{e}")
        content = f"操作未完成：{e}。"
    else:
        # 程序异常（网络断了、Chroma 连不上）：完整错误只写日志，给模型的消息不带内部细节
        # exc_info=e：把完整堆栈也写进日志，排查问题时看 logs/agent_日期.log
        logger.error(f"[工具调用] {call['name']} 执行异常：{e}", exc_info=e)
        content = "系统暂时无法完成这个操作，请稍后再试或联系人工客服。"
    return ToolMessage(
        content=content,
        tool_call_id=call["id"],
        name=call["name"],
        # status="error"：标记这是一次失败的工具调用（模型和界面都能据此区分成功 / 失败）
        status="error",
    )


def _log_done(call: dict, start: float) -> None:
    """记录工具用时。start：开始时 time.perf_counter() 的值"""
    cost_ms = (time.perf_counter() - start) * 1000
    # 用时主要看 search_knowledge（要请求向量模型 + Chroma，实测约 2 秒），其他工具读本地 json 只要几毫秒
    logger.info(f"[工具调用] {call['name']} 完成，用时 {cost_ms:.0f} ms")


class ToolCallGuard(AgentMiddleware):
    """
    包住每一次工具执行：日志 + 计时 + 异常转成错误 ToolMessage。
    注意：参数校验失败（模型填错格式）不会走到这里的 except —— 框架已经把它变成错误 ToolMessage 交给模型重试了
    """

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """
        同步版：命令行 main.py 走这里。
        request.tool_call：模型请求的这次调用 {"name", "args", "id"}
        handler：真正执行工具的函数（包括 Pydantic 参数校验）
        返回：工具正常执行的结果（ToolMessage 或 Command）；出异常时返回 _tool_error_message 构造的错误消息
        """
        call = request.tool_call  # {"name": 工具名, "args": 参数, "id": 调用 ID}
        logger.info(f"[工具调用] {call['name']} 参数 {call['args']}")
        start = time.perf_counter()
        try:
            result = handler(request)  # 真正执行工具
        except Exception as e:
            return _tool_error_message(call, e)
        _log_done(call, start)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """
        异步版：网页后端走这里。和同步版唯一的区别：handler 是异步函数，要 await 它。
        注意：我们的工具本身是同步函数（读 json、调 Chroma），框架在异步模式下会把它放进线程池执行，
        所以这里 await 的是「线程池里跑完」，工具代码一行都不用改。
        """
        call = request.tool_call
        logger.info(f"[工具调用] {call['name']} 参数 {call['args']}")
        start = time.perf_counter()
        try:
            result = await handler(request)
        except Exception as e:
            return _tool_error_message(call, e)
        _log_done(call, start)
        return result


# 实例名和原来的函数名一样：agent/agent.py 不用改
guard_tool_call = ToolCallGuard()
