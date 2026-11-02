"""
业务异常：services 层只管「业务对不对」，出错时抛这几种异常，
由上层（工具）决定怎么告诉模型。这样同一个 service 以后给 FastAPI 接口用时，可以换成 HTTP 状态码。

【在整体流程里的位置】
services/* 抛出 → 工具函数不捕获、直接往上冒 → agent/middleware.py 的 guard_tool_call 统一捕获：
    BusinessError 及子类 → 变成「操作未完成：<原因>」的 ToolMessage 交给模型，由模型转告用户（日志记 WARNING）
    其他异常（网络、Chroma 连不上等）→ 变成「系统暂时无法完成…」，不暴露内部细节（日志记 ERROR + 堆栈）
所以这里的异常信息要写成「用户能看懂的话」，因为它会被模型转述给用户。
"""


class BusinessError(Exception):
    """所有业务异常的父类。guard_tool_call 只认这个父类，新增业务异常时继承它即可"""


class NotFoundError(BusinessError):
    """查的东西不存在：订单、工单、用户。（以后接 FastAPI 可对应 HTTP 404）"""


class PermissionDeniedError(BusinessError):
    """没有权限：查别人的订单、普通用户改工单状态。（对应 HTTP 403）"""


class RuleViolationError(BusinessError):
    """违反业务规则：订单还没签收就报修、工单状态不能这样流转。（对应 HTTP 400/409）"""


class SummaryError(BusinessError):
    """
    【v2 网页版 · 阶段 5】会话小结生成失败：模型返回的小结格式不对。（网页接口对应 HTTP 502：上游模型的问题，不是请求的问题）
    和上面三个不同，它不是工具抛的，不会经过 guard_tool_call；由 routers/summary.py 捕获后转成 HTTP 错误。
    """
