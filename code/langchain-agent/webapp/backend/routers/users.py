"""
【v2 网页版新增】用户接口：GET /api/users（模拟登录用的用户列表）

页面左上角的下拉框调用它，列出张三、李四、王主管；选中谁，之后每个请求的 X-User-Id 就是谁。
和命令行 main.py 的 choose_user 菜单是同一个作用。真实项目没有这个接口，身份来自登录。
"""
from fastapi import APIRouter

from services.user_service import list_users
from webapp.backend.schemas import UserInfo

router = APIRouter(prefix="/users", tags=["用户"])


@router.get("", response_model=list[UserInfo])
def get_users() -> list[UserInfo]:
    """
    返回：全部用户的 user_id、name、role。
    response_model=list[UserInfo]：users.json 里还有 phone，UserInfo 没有这个字段，所以不会返回给前端。
    为什么这里用普通 def 而不是 async def：它只读一个本地 json，不需要 await 任何东西；
        FastAPI 会把普通 def 的接口放进线程池执行，不会卡住事件循环。两种写法 FastAPI 都支持。
    """
    return [UserInfo(**u) for u in list_users()]
