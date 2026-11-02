"""
【v2 网页版新增】路由（接口）：一个文件管一组相关的接口
    chat.py   POST /api/chat        发一句话，等 agent 跑完，返回回答（阶段 1：不流式）
    users.py  GET  /api/users       模拟登录用的用户列表
app.py 用 include_router 把它们挂到 /api 下面。
"""
