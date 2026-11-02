"""
【v2 网页版新增 · 阶段 2】流式输出：把 agent 运行过程中的事件，一条条推给浏览器

    protocol.py  前端事件协议：有哪些事件、每个事件带什么字段、怎么编码成 SSE 文本
    runner.py    跑 astream_events(version="v3")，把 LangChain 的原始事件翻译成前端事件

谁用它：routers/chat.py 的 POST /api/chat/stream
"""
