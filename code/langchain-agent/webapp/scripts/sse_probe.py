"""
【v2 网页版新增 · 阶段 2】命令行 SSE 探针：调用 /api/chat/stream，打印每条事件「到达的毫秒时间」

为什么需要（4 层验证的第 3 层：HTTP / SSE 层）：
    测试（test_api_stream.py）用的是假模型，只能证明「事件顺序对」，证明不了「真的是一个字一个字到的」。
    这个脚本连真实后端和 DeepSeek，看每条事件是什么时候到的：
        首个 token 时间 远小于 总时长 → 真流式（边生成边推）
        首个 token 时间 ≈ 总时长      → 假流式（被谁攒成一块再发，例如代理缓冲）
    再分别直连后端（:8001）和经过 Vite（:5173）各测一次：两者首个 token 时间只差几毫秒，说明 Vite 转发没有攒包。

用法（在 langchain-agent 根目录执行，后端要先启动）：
    ..\\..\\.venv\\Scripts\\python.exe webapp\\scripts\\sse_probe.py "我有哪些订单？"
    ..\\..\\.venv\\Scripts\\python.exe webapp\\scripts\\sse_probe.py "我有哪些订单？" --base http://127.0.0.1:8001   ← 直连后端
参数：
    message   要发送的话
    --user    以谁的身份（默认 U1001 张三）
    --thread  接着哪段对话聊；不传 = 新对话
    --base    请求发到哪：默认 http://127.0.0.1:5173（经过 Vite 转发，和浏览器走的路一样）
    --all     把每一条 token 都打印出来（默认只打印前 3 条，后面的只计数）
"""
import argparse
import json
import time

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="调用 /api/chat/stream，打印每条 SSE 事件的到达时间")
    parser.add_argument("message")
    parser.add_argument("--user", default="U1001")
    parser.add_argument("--thread", default=None)
    parser.add_argument("--base", default="http://127.0.0.1:5173")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    start = time.perf_counter()

    def ms() -> str:
        return f"[{(time.perf_counter() - start) * 1000:6.0f} ms]"

    first_token = None  # 首个 token 到达的时间（毫秒）
    last_token = None   # 最后一个 token 到达的时间（毫秒）
    tokens = 0          # token 事件条数
    event, text = None, []

    # trust_env=False：不走系统代理（你电脑上的 Clash），原因同 chat_probe.py
    with httpx.Client(base_url=args.base, trust_env=False, timeout=120) as client:
        # client.stream(...)：和 client.post 的区别是「不等响应结束」，响应头一到就进入 with，
        #   之后用 iter_lines() 边收边读。用 client.post 的话会等整个响应结束才返回，就看不出流式效果了
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={"thread_id": args.thread, "message": args.message},
            headers={"X-User-Id": args.user},
        ) as r:
            print(f"{ms()} 响应头到达：HTTP {r.status_code}，Content-Type: {r.headers.get('content-type')}")
            if r.status_code != 200:
                # 开始推流之前的错误（401 / 403 / 409 / 422）：响应体是普通 JSON
                print(r.read().decode())
                return
            # SSE 格式：event: 行 + data: 行 + 空行。逐行读，读到空行说明一条事件结束
            for line in r.iter_lines():
                if line.startswith("event: "):
                    event = line[len("event: "):]
                elif line.startswith("data: "):
                    data = json.loads(line[len("data: "):])
                    if event == "token":
                        tokens += 1
                        last_token = (time.perf_counter() - start) * 1000
                        if first_token is None:
                            first_token = last_token
                        text.append(data["text"])
                        if args.all or tokens <= 3:
                            print(f"{ms()} token          {data['text']!r}（第 {data['call']} 次模型调用）")
                        elif tokens == 4:
                            print(f"{ms()} token          ……（后面的 token 只计数不打印，加 --all 全部打印）")
                    elif event == "done":
                        # done 里带完整结果，太长了，只打印关键字段
                        brief = {k: data.get(k) for k in ("status", "thread_id", "sources", "token_usage")}
                        print(f"{ms()} done           {json.dumps(brief, ensure_ascii=False)}")
                    else:
                        print(f"{ms()} {event:<14} {json.dumps(data, ensure_ascii=False)}")

    total = (time.perf_counter() - start) * 1000
    print("\n—— 统计 ——")
    if first_token is None:
        print(f"没有收到 token；总时长 {total:.0f} ms")
    else:
        print(f"token 事件 {tokens} 条；首个 token {first_token:.0f} ms；最后一个 token {last_token:.0f} ms；总时长 {total:.0f} ms")
        # 判断标准：文字是不是「陆续」到达的。
        #   真流式：token 从第一条到最后一条之间隔了几百上千毫秒（模型一边生成一边推）
        #   假流式：所有 token 挤在同一时刻到达（被某一层攒成一块再发），间隔接近 0
        # 注意：不能用「首个 token 早不早」来判断 —— 调了工具的问题，要等模型决定调工具、工具跑完，
        #   第 2 次模型调用才开始说话，首个 token 本来就会晚（实测查订单约 2.4 秒，查知识库约 4 秒）
        spread = last_token - first_token
        verdict = "真流式（文字陆续到达）" if spread > 200 else "可能被攒成了一块（所有文字几乎同时到达），检查代理或转发层"
        print(f"文字陆续到达的时间跨度 {spread:.0f} ms → {verdict}")
    print(f"拼起来的文字：{''.join(text)[:200]}")


if __name__ == "__main__":
    main()
