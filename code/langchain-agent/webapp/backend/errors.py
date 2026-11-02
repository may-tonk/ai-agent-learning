"""
【v2 网页版新增 · 阶段 5】把模型异常翻译成 HTTP 错误（从 routers/chat.py 挪过来）

为什么单独放一个文件：阶段 1~4 只有对话接口会调用模型；阶段 5 的「生成小结」也要调用模型，
    同样可能遇到限流、超时、key 不对。两个路由都要用同一套翻译规则，就放到公共的地方，
    而不是在 summary.py 里复制一份（复制的两份迟早会改得不一样）。
谁用它：routers/chat.py（对话出错）、routers/summary.py（生成小结出错）
"""
from fastapi import HTTPException
from langchain_core.exceptions import (
    ContextOverflowError,
    ModelAuthenticationError,
    ModelConnectionError,
    ModelError,
    ModelRateLimitError,
    ModelTimeoutError,
)


def model_error_to_http(e: ModelError) -> HTTPException:
    """
    模型异常 → HTTP 错误。分类和命令行版 main.py 一样，只是从「打印提示」换成「返回状态码 + detail」。
    detail 会显示在页面上，所以写成用户能看懂的话；具体错误已经写进日志。
    状态码选法（真实项目的常见约定）：
        429 太频繁（前端可以稍后重试）
        502 上游（DeepSeek）出错 / 504 上游超时 —— 表示「不是你的请求有问题，是后端依赖的服务出问题」
        413 内容太长
    """
    if isinstance(e, ModelRateLimitError):
        return HTTPException(status_code=429, detail="请求太频繁，请稍后再试")
    if isinstance(e, (ModelConnectionError, ModelTimeoutError)):
        return HTTPException(status_code=504, detail="连不上模型服务或超时，请稍后再试")
    if isinstance(e, ContextOverflowError):
        return HTTPException(status_code=413, detail="对话太长了，请点「新会话」重新开始")
    if isinstance(e, ModelAuthenticationError):
        # 认证失败是后端配置问题（API key 不对），不要把细节告诉用户
        return HTTPException(status_code=502, detail="模型服务配置有误，请联系管理员")
    return HTTPException(status_code=502, detail="模型调用失败，请稍后再试")
