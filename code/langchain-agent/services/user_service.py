"""
用户查询：程序启动时根据登录的用户 ID 拿到姓名和角色

【在整体流程里的位置】只在「登录」时用到，不会被 agent / 模型调用：
    main.py 的 choose_user → list_users() 列出可选用户 → 组装成 UserContext 传给 agent
数据来自 data/users.json，每个用户有 user_id、name、role（customer / supervisor）。
"""
from services.data_store import read_json
from services.errors import NotFoundError


def get_user(user_id: str) -> dict:
    """
    按 user_id 查一个用户。
    返回：{"user_id": ..., "name": ..., "role": ...}
    异常：不存在 → NotFoundError
    """
    for user in read_json("users", default=[]):
        if user["user_id"] == user_id:
            return user
    raise NotFoundError(f"用户 {user_id} 不存在")


def list_users() -> list[dict]:
    """全部用户（main.py 的登录菜单用）。真实系统里没有这个函数，身份来自登录态 / token"""
    return read_json("users", default=[])
