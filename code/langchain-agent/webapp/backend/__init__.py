"""
【v2 网页版新增】FastAPI 后端：只负责「收请求 → 调 agent → 把结果整理成 JSON 返回」

启动（必须在 langchain-agent 根目录执行，Python 才能找到 agent/、services/）：
    ..\\..\\.venv\\Scripts\\python.exe -m uvicorn webapp.backend.app:app --port 8001 --reload
"""
