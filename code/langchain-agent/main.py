"""
程序入口：命令行版售后客服

运行：在项目根目录执行  python main.py
流程：选择登录用户 → 输入问题 → agent 回答（过程中会显示调用了哪些工具）
     遇到建工单 / 改工单状态，会暂停让你以「客服」身份审批

命令：
    /new      开始新对话（换一个 thread_id，之前的记忆不再带入）
    /state    查看 checkpointer 保存的 State：当前订单、累计 token、消息数
    /history  查看完整消息链（Human / AI / Tool 消息依次是什么）
    /summary  生成本次会话的结构化服务小结
    /user     切换登录用户
    /quit     退出

【在整体流程里的位置】最外层的「界面层」，只负责输入输出：
    启动：build_agent() 建好 agent（只建一次）→ choose_user() 登录 → 创建 CustomerServiceSession
    每个问题：session.ask(text) 产生事件 → render() 打印；遇到审批事件就问客服 y/n → session.resume()
业务逻辑和 agent 逻辑都不在这里，所以以后换成网页界面，只需要重写这个文件。

运行时你会看到两种输出混在一起：
    彩色的「客服：…」「[调用工具] …」是 render() 打印的对话内容
    「2026-10-23 ... - agent - INFO - ...」是 utils/logger_handler.py 打的日志（嫌乱可以把控制台日志级别调成 WARNING）
"""
import json
import os

from langchain_core.exceptions import (
    ContextOverflowError,
    ModelAuthenticationError,
    ModelConnectionError,
    ModelError,
    ModelRateLimitError,
    ModelTimeoutError,
)

from agent.agent import CustomerServiceSession, build_agent
from agent.state import UserContext
from services.summary_service import summarize_session
from services.user_service import list_users
from utils.logger_handler import logger

if os.name == "nt":
    os.system("")  # 让 Windows 命令行支持彩色输出

# ANSI 颜色码：灰色 = 过程信息，青色 = 客服回答，黄色 = 审批，绿色 = 用户输入 / 小结
GREY, CYAN, YELLOW, GREEN, RESET = "\033[90m", "\033[96m", "\033[93m", "\033[92m", "\033[0m"


def choose_user() -> UserContext:
    """
    命令行登录：列出 data/users.json 里的用户，输入序号选择。
    返回：UserContext，之后作为 context 传给 agent
    （真实系统里没有这一步，身份来自登录态，这里用菜单模拟）
    """
    users = list_users()
    print("\n请选择登录用户：")
    for i, u in enumerate(users, start=1):
        print(f"  {i}. {u['name']}（{u['user_id']}，{'客服主管' if u['role'] == 'supervisor' else '普通用户'}）")
    while True:
        choice = input("输入序号：").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(users):
            u = users[int(choice) - 1]
            # 用户身份由程序决定（真实系统里来自登录态），之后作为 context 传给 agent，模型改不了
            return UserContext(user_id=u["user_id"], user_name=u["name"], role=u["role"])


def render(events, session: CustomerServiceSession) -> None:
    """
    把 session 产生的事件打印出来；遇到审批就问一句，然后继续

    events：session.ask() 或 session.resume() 返回的事件生成器（事件格式见 agent/agent.py 的 CustomerServiceSession）
    session：当前会话，审批后要用它 resume
    流程：消费完一批事件 → 如果其中有审批请求，问客服 y/n → resume 得到新一批事件 → 继续循环，直到没有审批
    """
    sources = []
    printed_answer = False

    while True:
        approval = None
        for event in events:
            kind = event[0]
            if kind == "token":
                if not printed_answer:
                    print(f"{CYAN}客服：{RESET}", end="")
                    printed_answer = True
                print(event[1], end="", flush=True)
            elif kind == "tool_call":
                print(f"\n{GREY}  [调用工具] {event[1]} {json.dumps(event[2], ensure_ascii=False)}{RESET}")
            elif kind == "tool_result":
                _, name, content, artifact = event
                print(f"{GREY}  [工具结果] {name}：{str(content)[:80]}{'…' if len(str(content)) > 80 else ''}{RESET}")
                if name == "search_knowledge" and artifact:
                    sources.extend(artifact)
            elif kind == "approval":
                approval = event[1]
            elif kind == "final":
                print(f"{CYAN}客服：{RESET}{event[1]}")
                printed_answer = True

        if not approval:
            break

        # agent 已暂停，状态保存在 checkpointer 里；这里模拟后台客服审批
        print(f"\n{YELLOW}【需要客服审批】{RESET}")
        for req in approval:
            print(f"  操作：{req['name']}")
            print(f"  参数：{json.dumps(req['args'], ensure_ascii=False)}")
        ok = input(f"{YELLOW}是否批准？(y/n)：{RESET}").strip().lower() == "y"
        reason = "" if ok else input("拒绝原因：").strip()
        events = session.resume(ok, reason)

    if printed_answer:
        print()
    # artifact 里的出处：模型没看到这些信息，是程序直接拿来展示的
    if sources:
        names = sorted({s["source"] for s in sources})
        print(f"{GREY}  参考资料：{'、'.join(names)}{RESET}")


def show_state(session: CustomerServiceSession) -> None:
    """/state 命令：查看 checkpointer 里保存的 State（调 summary_trigger_tokens 时可以用它看累计 token）"""
    state = session.state()
    print(f"{GREY}thread_id：{session.thread_id}")
    print(f"当前订单：{state.get('current_order_id', '暂无')}")
    print(f"累计 token：{state.get('token_usage', {})}")
    print(f"消息条数：{len(state.get('messages', []))}{RESET}")


def show_history(session: CustomerServiceSession) -> None:
    """/history 命令：按顺序列出消息链，能看到 AIMessage 的 tool_calls 和 ToolMessage 的 tool_call_id 是怎么对上的"""
    for i, m in enumerate(session.state().get("messages", []), start=1):
        extra = ""
        if getattr(m, "tool_calls", None):
            extra = f" tool_calls={[(c['name'], c['id']) for c in m.tool_calls]}"
        if m.type == "tool":
            extra = f" tool_call_id={m.tool_call_id}"
        print(f"{GREY}{i:>2}. {type(m).__name__}{extra}｜{str(m.content)[:60]}{RESET}")


def show_summary(session: CustomerServiceSession) -> None:
    """/summary 命令：用结构化输出生成本次会话的服务小结（会额外调用一次模型）"""
    messages = session.state().get("messages", [])
    if not messages:
        print("还没有对话内容。")
        return
    summary = summarize_session(messages)  # 返回的是 ServiceSummary 对象，不是字符串
    print(f"{GREEN}{json.dumps(summary.model_dump(), ensure_ascii=False, indent=2)}{RESET}")


def main() -> None:
    """命令行主循环：读一行输入 → 是命令就执行命令，否则交给 agent 回答"""
    agent = build_agent()  # 整个程序只建一个 agent；不同用户、不同对话靠 context 和 thread_id 区分
    session = CustomerServiceSession(agent, choose_user())
    print(f"\n已登录：{session.context.user_name}。输入问题开始咨询，/quit 退出。\n")

    while True:
        text = input(f"{GREEN}你：{RESET}").strip()
        if not text:
            continue
        if text == "/quit":
            break
        if text == "/new":
            print(f"{GREY}新对话 thread_id = {session.new_thread()}{RESET}")
            continue
        if text == "/user":
            session = CustomerServiceSession(agent, choose_user())
            continue
        if text == "/state":
            show_state(session)
            continue
        if text == "/history":
            show_history(session)
            continue
        if text == "/summary":
            show_summary(session)
            continue

        try:
            render(session.ask(text), session)
        # 按 LangChain 标准异常分类处理：不同原因，处理方式完全不同
        except ModelAuthenticationError:
            print("模型认证失败：检查 .env 里的 DEEPSEEK_API_KEY 是否正确（重试没用）")
        except ModelRateLimitError:
            print("请求太频繁被限流（429）：稍等再试")
        except (ModelConnectionError, ModelTimeoutError):
            print("连不上模型服务或超时：检查网络 / 代理")
        except ContextOverflowError:
            print("对话太长超过模型上下文：输入 /new 开始新对话")
        except ModelError as e:
            print(f"模型调用失败：{type(e).__name__}: {e}")
        except Exception as e:
            logger.error(f"未知错误：{e}", exc_info=True)
            print(f"出错了：{e}")


if __name__ == "__main__":
    main()
