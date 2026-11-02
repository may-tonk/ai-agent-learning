"""
【v2 网页版新增】网页版的全部代码：backend/（FastAPI 后端）和 frontend/（React 前端）

webapp/ 整个是「界面层」，和命令行的 main.py 地位一样：只调用 agent/ 和 services/，不写业务逻辑。
以后不要网页版了，删掉这个文件夹即可，agent/ 一行不用改。
这个 __init__.py 让 Python 把 webapp 当成包，才能用 webapp.backend.app 这种点号路径导入。
"""
