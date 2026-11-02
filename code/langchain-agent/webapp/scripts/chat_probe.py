"""
【v2 网页版新增】命令行接口探针：不打开浏览器，直接调用 /api/chat，看后端返回了什么、用了多久

为什么需要：页面出问题时，先用它判断是「后端的问题」还是「前端的问题」——
    探针正常、页面不正常 → 查前端；探针也不正常 → 查后端日志。真实项目里排查接口问题也是先绕开页面直接调接口。

用法（在 langchain-agent 根目录执行，后端要先启动）：
    ..\\..\\.venv\\Scripts\\python.exe webapp\\scripts\\chat_probe.py "我有哪些订单？"
    ..\\..\\.venv\\Scripts\\python.exe webapp\\scripts\\chat_probe.py "我刚才问了什么？" --thread U1001-xxxxxxxx
    ..\\..\\.venv\\Scripts\\python.exe webapp\\scripts\\chat_probe.py "你好" --base http://127.0.0.1:8001   ← 直连后端，不经过 Vite
参数：
    message   要发送的话
    --user    以谁的身份（默认 U1001 张三）
    --thread  接着哪段对话聊；不传 = 新对话
    --base    请求发到哪：默认 http://127.0.0.1:5173（经过 Vite 转发，和浏览器走的路一样）
流式接口用旁边的 sse_probe.py。
"""
import argparse
import json
import time

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="调用 /api/chat 并打印结果")
    parser.add_argument("message")
    parser.add_argument("--user", default="U1001")
    parser.add_argument("--thread", default=None)
    parser.add_argument("--base", default="http://127.0.0.1:5173")
    args = parser.parse_args()

    start = time.perf_counter()
    # trust_env=False：不读系统代理设置。
    # 注意：你电脑上开着 Clash（127.0.0.1:7890），如果请求本机地址也走代理，会失败或变慢，所以这里强制直连
    # timeout=120：agent 一轮可能要调几次模型 + 检索，默认 5 秒会超时
    with httpx.Client(base_url=args.base, trust_env=False, timeout=120) as client:
        r = client.post(
            "/api/chat",
            json={"thread_id": args.thread, "message": args.message},
            headers={"X-User-Id": args.user},
        )
    cost = time.perf_counter() - start

    print(f"HTTP {r.status_code}，用时 {cost:.1f} 秒")
    # ensure_ascii=False：中文原样显示，不变成 中 这种转义
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
