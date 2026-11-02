"""
【v2 网页版新增】依赖注入：路由函数需要的「公共东西」从这里拿

【依赖注入是什么】路由函数在参数里写 user: UserContext = Depends(get_current_user)，
FastAPI 每次收到请求时会先调用 get_current_user，把返回值填进 user 参数，再调用路由函数。
好处：
    ① 「怎么识别当前用户」只写一处，所有接口共用；以后换成真实登录（JWT），只改这个文件
    ② 测试时可以用 app.dependency_overrides 把它换成假的，不用改路由代码
类比：路由函数是「窗口办事员」，依赖注入是「进门前的安检和取号」，办事员只管办事。

【在整体流程里的位置】
    浏览器请求 → FastAPI → 先跑 Depends 里的函数（本文件）→ 再跑 routers/*.py 的路由函数
"""
from fastapi import Depends, Header, HTTPException, Path, Request
from langchain_core.language_models import BaseChatModel

from agent.state import UserContext
from services import user_service
from services.errors import NotFoundError
from webapp.backend.repositories.messages import MessageRepository
from webapp.backend.repositories.summaries import SummaryRepository
from webapp.backend.repositories.threads import ThreadRepository
from webapp.backend.schemas import THREAD_ID_PATTERN


def get_agent(request: Request):
    """
    取出启动时建好的 agent。
    request.app.state：FastAPI 提供的「全局储物柜」，app.py 的 lifespan 启动时把 agent 放进去
    返回：build_agent() 的返回值（整个后端共用一个 agent，不同用户、不同对话靠 context 和 thread_id 区分）
    为什么不在每个请求里 build_agent()：建 agent 要创建模型、编译图，每次都建既慢又浪费
    """
    return request.app.state.agent


def get_current_user(x_user_id: str | None = Header(default=None)) -> UserContext:
    """
    从请求头 X-User-Id 识别当前用户（模拟登录）。

    x_user_id：FastAPI 会自动把参数名里的下划线换成连字符，对应请求头 X-User-Id（大小写不敏感）
    返回：UserContext，之后作为 context 传给 agent（工具和中间件从 runtime.context 读）
    异常：没带请求头、用户不存在 → 401（未登录）

    注意：这只是学习用的模拟登录，任何人改个请求头就能冒充别人。
    真实项目的做法：登录接口校验密码后签发 JWT（一段带签名的令牌），前端每次请求带
        Authorization: Bearer <令牌>；这里改成校验签名、从令牌里取 user_id，伪造不了。
    换成 JWT 时，只改这个函数，路由和 agent 都不用动。
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="未登录：缺少 X-User-Id 请求头")
    try:
        u = user_service.get_user(x_user_id)
    except NotFoundError:
        raise HTTPException(status_code=401, detail=f"未登录：用户 {x_user_id} 不存在")
    # 身份由后端查出来，而不是让前端直接传 name、role：前端传的东西都可以被篡改
    return UserContext(user_id=u["user_id"], user_name=u["name"], role=u["role"])


def get_threads(request: Request) -> ThreadRepository:
    """【阶段 4】会话表的仓库（app.py 启动时建好放进 app.state，和 get_agent 同一个思路）"""
    return request.app.state.threads


def get_messages(request: Request) -> MessageRepository:
    """【阶段 4】消息表的仓库"""
    return request.app.state.messages


def get_summaries(request: Request) -> SummaryRepository:
    """【阶段 5】小结表的仓库"""
    return request.app.state.summaries


def get_summary_model(request: Request) -> BaseChatModel:
    """【阶段 5】生成小结用的模型（config/model.yml 的 summary 段；测试时是假模型），app.py 启动时建好"""
    return request.app.state.summary_model


async def check_thread_owner(threads: ThreadRepository, thread_id: str, user: UserContext) -> dict:
    """
    【阶段 4】检查这段对话存在、并且属于当前用户，返回会话表里的那一行。
    异常：不存在（或已删除）→ 404；别人的 → 403

    阶段 1~3 是看 thread_id 是不是以 "<user_id>-" 开头；现在查会话表的 user_id 列 —— 真实项目都是查表判断，
    因为 ID 格式随时可能变（比如换成纯随机的 UUID），「属于谁」必须是一条明确记下来的数据。
    注意：有些项目对「别人的会话」也返回 404，连「这个 ID 存在」都不透露；这里分开返回，方便学习时看出是哪种情况。
    """
    row = await threads.get(thread_id)
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在（可能已经删除了）")
    if row["user_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="无权访问这段对话")
    return row


async def get_owned_thread(
    thread_id: str = Path(pattern=THREAD_ID_PATTERN),
    user: UserContext = Depends(get_current_user),
    threads: ThreadRepository = Depends(get_threads),
) -> str:
    """
    【阶段 4】给 /api/threads/{thread_id}/... 这些接口用的依赖：从路径里取出 thread_id，检查归属，返回 thread_id。
    依赖里面还可以再写 Depends（这里用了 get_current_user、get_threads），FastAPI 会一层层解析；
    同一个请求里 get_current_user 只会执行一次（FastAPI 会缓存），路由函数里再写一遍也不会重复查用户。
    这样每个接口只要写 thread_id: str = Depends(get_owned_thread)，检查就不会漏。
    """
    await check_thread_owner(threads, thread_id, user)
    return thread_id
