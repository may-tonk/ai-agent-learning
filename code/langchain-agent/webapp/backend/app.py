"""
【v2 网页版新增】FastAPI 后端入口：创建 app，启动时建好 checkpointer 和 agent

启动（在 langchain-agent 根目录执行）：
    ..\\..\\.venv\\Scripts\\python.exe -m uvicorn webapp.backend.app:app --port 8001 --reload
    webapp.backend.app:app 的意思：导入 webapp/backend/app.py 这个模块，用里面名叫 app 的对象
    --port 8001：不用 8000，避免和 Chroma（Ubuntu 上的 8000）混淆
    --reload：改了 .py 文件自动重启（只在开发时用）
启动后可以打开 http://127.0.0.1:8001/docs 看自动生成的接口文档，并直接在页面上试调用。

【在整体流程里的位置】
    uvicorn 启动 → 导入本文件 → 执行 lifespan 的前半段（打开 checkpointer 和业务库、build_agent）
    → 开始接收请求：/api/chat → routers/chat.py，/api/users → routers/users.py，/api/threads → routers/threads.py（阶段 4）
      /api/threads/{id}/summary → routers/summary.py（阶段 5）
    → Ctrl+C 关闭 → 执行 lifespan 的后半段（关闭 SQLite 连接）

和命令行 main.py 的对应关系：
    main.py：agent = build_agent()  →  while 循环读输入
    这里   ：lifespan 里 build_agent() 一次  →  uvicorn 负责「循环接收请求」
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.language_models import BaseChatModel

from agent.agent import build_agent
from model.factory import build_chat_model
from utils.config_handler import load_yaml
from utils.logger_handler import logger
from utils.path_tool import get_abs_path
from webapp.backend.checkpointer import open_checkpointer
from webapp.backend.db import open_db
from webapp.backend.repositories.messages import MessageRepository
from webapp.backend.repositories.summaries import SummaryRepository
from webapp.backend.repositories.threads import ThreadRepository
from webapp.backend.routers import chat, summary, threads, users

# 网页后端的配置（端口之外的东西：CORS、checkpointer），见 webapp/backend/config/web.yml
web_conf = load_yaml("webapp/backend/config/web.yml")


def create_app(model: BaseChatModel | None = None, checkpointer_conf: dict | None = None) -> FastAPI:
    """
    创建 FastAPI 应用（「工厂函数」写法）。

    model：默认 None = 用 config/model.yml 的真实模型；测试时传入假模型（tests/fakes.py）
    checkpointer_conf：默认用 web.yml 的 checkpointer 段；测试时传 {"kind": "memory"} 或临时 SQLite 文件
    返回：配置好的 FastAPI 对象

    为什么写成函数而不是直接在模块里 app = FastAPI(...)：
        测试要用「假模型 + 临时数据库」造一个 app，正式运行用「真模型 + 正式数据库」造一个 app。
        写成工厂函数，两种情况调用时传不同参数即可，不用改代码 —— 真实项目里很常见的写法。
    """
    ckpt_conf = checkpointer_conf or web_conf["checkpointer"]
    # 【阶段 4】会话表、消息表和 checkpointer 放在同一个 SQLite 文件里（不同的表）；
    #   checkpointer 用内存（测试）时，业务表也用内存数据库，测试之间互不影响
    db_path = os.path.normpath(get_abs_path(ckpt_conf["sqlite_path"])) if ckpt_conf["kind"] == "sqlite" else ":memory:"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """
        生命周期：yield 之前 = 启动时执行一次；yield 之后 = 关闭时执行一次。
        为什么在这里建 agent，而不是在模块顶层：
            AsyncSqliteSaver 要在事件循环里打开（它是异步连接），而事件循环是 uvicorn 启动后才有的；
            放在 lifespan 里，打开和关闭也能成对出现（async with 保证关闭）。
        """
        # 一个 async with 可以同时打开两个资源，关闭时按相反顺序关
        async with open_checkpointer(ckpt_conf) as saver, open_db(db_path) as conn:
            # 【阶段 4】数据层：两个仓库共用一个连接，路由通过 deps.get_threads / get_messages 取用
            app.state.threads = ThreadRepository(conn)
            app.state.messages = MessageRepository(conn)
            app.state.summaries = SummaryRepository(conn)  # 【阶段 5】
            # 【阶段 5】小结用的模型：测试时和 agent 用同一个假模型；真实运行用 model.yml 的 summary 段（temperature 0）
            #   启动时建一次，所有请求共用（和 agent 一样，不在每个请求里新建）
            app.state.summary_model = model or build_chat_model("summary")
            # use_backup_models：真实运行时启用摘要和备用模型；测试用假模型时关掉（避免创建真实模型）
            app.state.agent = build_agent(model=model, checkpointer=saver, use_backup_models=model is None)
            app.state.checkpointer_kind = ckpt_conf["kind"]
            logger.info("[网页后端] 启动完成：agent 已创建")
            yield  # ← 后端在这里「停住」并处理请求，直到收到关闭信号
        logger.info("[网页后端] 已关闭：checkpointer 连接已释放")

    # title / version 会显示在 /docs 接口文档的页面顶部
    app = FastAPI(title="智扫通售后客服 API", version="2.0.0", lifespan=lifespan)

    # CORS 中间件：允许 web.yml 里列出的网页地址跨域调用（原因见 web.yml 的注释）
    # 注意：这是 FastAPI（HTTP 层）的中间件，和 agent/middleware.py（agent 循环里的中间件）不是一回事
    app.add_middleware(
        CORSMiddleware,
        allow_origins=web_conf["cors_origins"],
        allow_methods=["*"],
        allow_headers=["*"],  # 允许自定义请求头 X-User-Id
    )

    # 把各组接口挂到 /api 下：chat.router 的 /chat → /api/chat
    # 所有接口都以 /api 开头：Vite 只需要转发 /api 开头的请求，页面文件和接口不会混在一起
    app.include_router(chat.router, prefix="/api")
    app.include_router(users.router, prefix="/api")
    app.include_router(threads.router, prefix="/api")  # 【阶段 4】会话列表、历史、State、删除；【阶段 5】消息链
    app.include_router(summary.router, prefix="/api")  # 【阶段 5】会话小结

    @app.get("/api/health", tags=["系统"])
    async def health(request: Request) -> dict:
        """健康检查：前端、运维脚本用它判断后端是否活着、记忆存在哪"""
        return {"status": "ok", "checkpointer": request.app.state.checkpointer_kind}

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """
        兜底：路由里没处理到的异常（代码 bug、数据库出错）都走到这里。
        完整堆栈只写日志，返回给页面的是一句通用提示 —— 不把内部细节（文件路径、SQL）暴露给用户。
        注意：HTTPException（我们主动抛的 401 / 403 / 409 等）不走这里，FastAPI 会原样返回
        """
        logger.error(f"[网页后端] 未处理的异常：{request.method} {request.url.path}：{exc}", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请稍后再试"})

    return app


# uvicorn webapp.backend.app:app 找的就是这个对象（用真实模型 + web.yml 的配置）
app = create_app()
