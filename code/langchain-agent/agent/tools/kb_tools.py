"""
知识库工具

【Tools + Messages 模块：content_and_artifact】
response_format="content_and_artifact" 时，工具函数返回一个二元组 (content, artifact)：
- content：交给模型看的内容 → 变成 ToolMessage.content，会算进 token
- artifact：只给程序用的数据（来源文件、向量距离、重排分数、原排名）→ 变成 ToolMessage.artifact，不会发给模型
main.py 打印回答后，从 artifact 里取出处显示给用户，模型不需要也看不到这些分数。

【在整体流程里的位置】RAG 的入口：模型判断用户在问产品使用 / 故障 / 保养问题 → 调用 search_knowledge
→ services/kb_service.search（① 召回 10 条 → ② 重排 → ③ 只留最相关的 3 条）→ 片段作为 ToolMessage 回到模型 → 模型据此组织回答

【query 是谁写的】不是用户的原话，而是模型「改写」过的检索词：参数说明（agent/schemas.py 的 SearchKnowledgeInput）
要求模型改写成包含关键词的问句。实测用户问「扫地机器人总是迷路怎么办」，模型传进来的是
「扫地机器人总是迷路 导航异常 重新建图 解决方法」—— 关键词越全，召回越准（这一步在 RAG 里叫 query 改写）

【检索结果怎么交给模型】只把原文按「【资料1】【资料2】…」编号拼成一段文字（content），
距离、重排分数这些数字不给模型（模型用不上，还浪费 token），放在 artifact 里给程序用

【v2 网页版 · 阶段 6：检索进度】
    get_stream_writer()：LangGraph 提供的「往流里写自定义数据」的函数（lessons/05 第 5 节演示过）。
    这里把它包成 kb_service.search 要的进度回调：检索每走一步，就往流里写一条 {tool_call_id, step, status, message}。
    网页后端在 streaming/runner.py 里把这些数据翻译成 tool_progress 事件推给浏览器，工具标签下面实时显示进度。
    带上 tool_call_id：同一轮模型可能同时调用两次检索，前端靠它知道进度属于哪个工具标签。
    什么时候写了也没人收：命令行版 agent.stream(stream_mode=["messages", "updates"]) 没要 custom 这种流，
        这时 get_stream_writer() 返回的是一个「什么都不做」的函数，写了等于没写，不会出错。

【重要】@tool 函数的 docstring 就是发给模型的「工具说明」，模型靠它决定什么时候调用这个工具。
所以这类函数的讲解统一写成 # 注释，不改 docstring（改 docstring = 改模型的行为）。
"""
from langchain.tools import ToolRuntime, tool
from langgraph.config import get_stream_writer

from agent.schemas import SearchKnowledgeInput
from services import kb_service


# @tool 的参数：
#   args_schema=SearchKnowledgeInput  参数的 JSON Schema 和校验规则来自这个 Pydantic 类（不从函数签名推断）
#   response_format="content_and_artifact"  函数返回 (content, artifact) 二元组，见文件开头说明
# 【阶段 6】加了 runtime 参数：不是为了知道用户是谁，而是要 runtime.tool_call_id（这次工具调用的 ID），写进进度里。
#   runtime 由框架自动传入，不会出现在发给模型的参数 schema 里（模型看到的工具说明和参数都没变）
# 返回：(给模型看的文字, 给程序用的 hits 列表)
#   hits 来自 kb_service.search，已经按重排分数从高到低排好、最多 k=3 条、低于 min_score 的已经丢掉
@tool(args_schema=SearchKnowledgeInput, response_format="content_and_artifact")
def search_knowledge(query: str, runtime: ToolRuntime) -> tuple[str, list[dict]]:
    """检索扫地机器人产品知识库：使用方法、故障排除、维护保养、选购建议。
    用户问「怎么用、为什么会这样、怎么处理、怎么保养、选哪款」时调用。
    不能用来查订单、物流、保修状态。"""
    # 【阶段 6】注意：get_stream_writer() 只能在 agent 运行过程中调用（实测：在 agent 外面直接调用会报
    #   RuntimeError: Called get_config outside of a runnable context）。工具总是由 agent 调用，所以这里没问题
    writer = get_stream_writer()

    def report(step: str, status: str, message: str) -> None:
        writer({"tool_call_id": runtime.tool_call_id, "step": step, "status": status, "message": message})

    hits = kb_service.search(query, on_progress=report)

    if not hits:
        # 明确告诉模型「没找到、别编」：否则模型容易凭常识编一个答案，看起来像是知识库说的
        return "知识库中没有找到相关内容。请如实告诉用户，不要编造。", []

    # 给模型的内容：编号 + 原文，模型回答时可以说「根据资料1」
    content = "\n\n".join(f"【资料{i}】{h['content']}" for i, h in enumerate(hits, start=1))
    return content, hits
