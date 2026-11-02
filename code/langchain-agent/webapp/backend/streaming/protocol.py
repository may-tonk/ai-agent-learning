"""
【v2 网页版新增 · 阶段 2】前端事件协议：后端推给浏览器的每一条事件叫什么、带什么数据

【为什么要自己定一套协议，而不是把 LangChain 的事件原样转发】
    ① LangChain 的原始事件很多很杂（一轮几十条，还有 values 这种整份 State），浏览器只需要其中几种
    ② 原始事件里有内部数据（完整 State、别的用户看不到的字段），原样转发等于把后端内部暴露给前端
    ③ LangChain 升级时事件格式可能变（v3 现在还是实验性接口）；有了自己的协议，只改 runner.py 一处翻译，前端不用动
    真实项目都是这样做：后端定一份「前后端合同」，前端只认这份合同。

【SSE（Server-Sent Events）是什么】
    一种「服务器一条条往浏览器推文字」的 HTTP 格式：响应头 Content-Type: text/event-stream，
    连接一直开着，服务器每有一条事件就写一段：
        event: token                     ← 事件名
        data: {"text": "您好", "call": 1} ← 数据（我们统一用 JSON）
        （空行）                          ← 一个空行表示这条事件结束
    浏览器边收边解析（前端 src/api/sse.js），不用等整个响应结束。

【事件一览】（一次提问的典型顺序：run_started → token… → tool_started → tool_finished → token… → done）
    run_started        收到问题、开始运行         {thread_id}
    token              模型吐出一段文字           {text, call}   call = 这一轮第几次模型调用（从 1 开始）
    tool_started       工具开始执行               {id, name, args}
    tool_progress      工具执行中的进度（阶段 6） {id, step, status, message}   目前只有检索知识库会发：
                       step=recall / rerank，status=running / done，message 是给人看的一句话；同一个 step 先 running 后 done
    tool_finished      工具执行完                 {id, name, ok, sources}   ok=False 表示工具出错（中间件转成了错误消息）
    approval_required  停在了需要审批的操作上     {pending: [{name, args}]}
    error              运行出错                   {message}      给用户看的话，细节只写日志
    done               一定是最后一条             {status, ...ChatResponse 的全部字段}
                       status：completed 正常结束 / interrupted 停在审批上 / error 出错

谁用它：streaming/runner.py（产生事件）、routers/chat.py（编码后发出去）
"""
import json

# 事件名集中定义成常量：写错名字时 Python 直接报 NameError，比字符串拼错了悄悄失效更容易发现
RUN_STARTED = "run_started"
TOKEN = "token"
TOOL_STARTED = "tool_started"
TOOL_FINISHED = "tool_finished"
TOOL_PROGRESS = "tool_progress"  # 【阶段 6】
APPROVAL_REQUIRED = "approval_required"
ERROR = "error"
DONE = "done"


def encode_sse(event: str, data: dict) -> str:
    """
    把一条事件编码成 SSE 文本。

    event：事件名（上面的常量）
    data：要发给前端的数据，会转成 JSON
    返回：形如 "event: token\\ndata: {...}\\n\\n" 的字符串

    ensure_ascii=False：中文原样输出，不转成 \\u4f60 这种转义（体积更小，调试时也看得懂）
    JSON 里不会有真正的换行符（字符串里的换行会被转义成 \\n），所以 data 一定只占一行，符合 SSE 格式
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
