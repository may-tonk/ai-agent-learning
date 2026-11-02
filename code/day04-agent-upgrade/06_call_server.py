"""
Day 4 · 06：用代码调用 server.py 的各个接口

先在一个终端启动服务：python code/day04-agent-upgrade/server.py
再在另一个终端运行：  python code/day04-agent-upgrade/06_call_server.py

用的是 httpx（安装 openai 时已经一起装好了），它和 requests 很像，但同时支持同步和异步。

1. def vs async def：同时发 5 个"等 1 秒"的请求，看三个接口各要多久
2. Pydantic 在接口边界的校验：故意传错误参数，看 422 返回了什么
3. /tickets/analyze：结构化工单分析
4. /chat：读取 SSE 流，边收边打印
"""
import asyncio
import json
import time

import httpx

BASE = "http://127.0.0.1:8000"


def title(text):
    print(f"\n{'=' * 70}\n{text}\n{'=' * 70}")


async def part1(client):
    title("1. 同时发 5 个请求，每个接口内部都要等 1 秒")
    for path in ["/demo/async-await", "/demo/sync", "/demo/async-blocking"]:
        t = time.perf_counter()
        await asyncio.gather(*(client.get(path) for _ in range(5)))
        print(f"  {path:<22} 总耗时 {time.perf_counter() - t:.2f}s")
    print("观察：async-await 和 sync 约 1 秒（5 个请求同时在等）；"
          "async-blocking 约 5 秒（事件循环被 time.sleep 卡住，只能一个一个处理）")


async def part2(client):
    title("2. 传错误参数：FastAPI 用 Pydantic 自动校验，函数根本不会执行")
    r = await client.post("/tickets/analyze", json={"text": ""})
    print(f"  POST /tickets/analyze  text 为空 → {r.status_code}\n  {r.json()}")
    r = await client.get("/orders/abc")
    print(f"  GET /orders/abc  订单号格式错 → {r.status_code}\n  {r.json()}")
    r = await client.get("/orders/ORD999999")
    print(f"  GET /orders/ORD999999  格式对但不存在 → {r.status_code}  {r.json()}")
    r = await client.get("/orders/ORD100023")
    print(f"  GET /orders/ORD100023  正常 → {r.status_code}  {json.dumps(r.json(), ensure_ascii=False)[:100]}...")


async def part3(client):
    title("3. 结构化工单分析")
    r = await client.post("/tickets/analyze", json={"text": "ORD100031 的键盘用了两天就坏了，太失望了！"})
    print(f"  状态码 {r.status_code}")
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))


async def part4(client):
    title("4. /chat 流式对话（SSE）")
    body = {"message": "我是 alice@example.com，帮我看看我的订单都到了没有？"}
    print(f"客户：{body['message']}\n客服：", end="")
    # client.stream：不等响应全部到达，边收边处理
    async with client.stream("POST", "/chat", json=body) as resp:
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):     # SSE 消息之间的空行，跳过
                continue
            event = json.loads(line[len("data: "):])
            if event["type"] == "delta":
                print(event["text"], end="", flush=True)
            elif event["type"] == "tool_call":
                print(f"\n  [调用工具] {event['name']}({event['arguments']})")
            elif event["type"] == "tool_result":
                print(f"  [{'拦截' if event['blocked'] else '结果'}] {event['content'][:80]}")
            elif event["type"] == "done":
                print(f"\n  [完成] 共 {event['steps']} 步，输入 {event['prompt_tokens']} / 输出 {event['completion_tokens']} tokens")
            elif event["type"] == "error":
                print(f"\n  [错误] {event['message']}")


async def main():
    # trust_env=False：不使用系统代理设置，访问本机服务时避免被代理拦住
    async with httpx.AsyncClient(base_url=BASE, timeout=60, trust_env=False) as client:
        try:
            await client.get("/docs")
        except httpx.ConnectError:
            print("连不上 http://127.0.0.1:8000 ：请先在另一个终端运行 python code/day04-agent-upgrade/server.py")
            return
        await part1(client)
        await part2(client)
        await part3(client)
        await part4(client)


if __name__ == "__main__":
    asyncio.run(main())
