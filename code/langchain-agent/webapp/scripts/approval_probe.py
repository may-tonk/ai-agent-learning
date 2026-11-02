"""
【v2 网页版新增 · 阶段 3】命令行探针：用真实后端 + 真实 DeepSeek 走一遍「审批」和「停止」

为什么需要：test_api_resume.py 用的是假模型，证明的是程序逻辑；这个脚本验证的是真实情况：
    approve  报修 → 停在审批上（approval_required）→ POST /api/chat/resume 批准 → 工具真的执行、模型接着回答
    reject   报修 → 停在审批上 → 拒绝并给理由 → 工具不执行，模型根据理由回复
    stop     问一个要查知识库的问题，一看到 tool_started 就断开连接（等于网页上点「停止」）
             → 再在同一段对话里问一句：能正常回答，说明后端补好了存档（否则 DeepSeek 会报 400）
             后端窗口里应该能看到「[流式] … 取消这次运行」「[网页] 上一轮被停止，补了 1 条工具结果」两行日志

用法（在 langchain-agent 根目录执行，后端和 Vite 要先启动）：
    ..\\..\\.venv\\Scripts\\python.exe webapp\\scripts\\approval_probe.py approve
    ..\\..\\.venv\\Scripts\\python.exe webapp\\scripts\\approval_probe.py reject
    ..\\..\\.venv\\Scripts\\python.exe webapp\\scripts\\approval_probe.py stop
参数：
    --user  以谁的身份（默认 U1001 张三，名下有订单 SO20260312）
    --base  请求发到哪：默认 http://127.0.0.1:5173（经过 Vite 转发，和浏览器走的路一样）
注意：approve 会真的创建一张报修单（写进 data/runtime/ 下的工单文件，和命令行版批准后一样）
"""
import argparse
import json
import time

import httpx

REPAIR = "我的订单 SO20260312 那台扫拖一体机，拖地的时候一直漏水，帮我提交报修"
CONFIRM = "大概上周开始的，水箱底部一直往外渗水，信息就这些，请直接帮我提交报修单"
QUESTION = "扫地机器人回不了充电座怎么办？"


def run(client, url, body, user, stop_on=None):
    """
    发一次流式请求，打印每条事件（token 只计数），返回 (thread_id, 最后一条 done 的数据 或 None)
    stop_on：看到这个事件名就立刻断开连接（模拟「停止」按钮）
    """
    start = time.perf_counter()
    thread_id, done, event, tokens = None, None, None, 0
    with client.stream("POST", url, json=body, headers={"X-User-Id": user}) as r:
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}：{r.read().decode()}")
            return thread_id, None
        for line in r.iter_lines():
            if line.startswith("event: "):
                event = line[len("event: "):]
                continue
            if not line.startswith("data: "):
                continue
            data = json.loads(line[len("data: "):])
            t = f"[{(time.perf_counter() - start) * 1000:6.0f} ms]"
            if event == "token":
                tokens += 1
                continue
            if event == "run_started":
                thread_id = data["thread_id"]
            if event == "done":
                done = data
                print(f"  {t} done  status={data['status']}  （此前 token {tokens} 条）")
                print(f"           回答：{data.get('answer', '')[:120]}")
                continue
            print(f"  {t} {event}  {json.dumps(data, ensure_ascii=False)[:150]}")
            if event == stop_on:
                # 离开 with 块，httpx 关闭连接 —— 和浏览器里 AbortController.abort() 的效果一样
                print(f"  {t} → 断开连接（模拟点了「停止」）")
                break
    return thread_id, done


def main() -> None:
    parser = argparse.ArgumentParser(description="走一遍审批 / 停止流程")
    parser.add_argument("case", choices=["approve", "reject", "stop"])
    parser.add_argument("--user", default="U1001")
    parser.add_argument("--base", default="http://127.0.0.1:5173")
    args = parser.parse_args()

    # trust_env=False：不走系统代理（你电脑上的 Clash），原因同 chat_probe.py
    with httpx.Client(base_url=args.base, trust_env=False, timeout=120) as client:
        if args.case in ("approve", "reject"):
            print(f"① 提问：{REPAIR}")
            tid, done = run(client, "/api/chat/stream", {"thread_id": None, "message": REPAIR}, args.user)
            if done and done["status"] == "completed":
                # 实测：DeepSeek 经常先查保修、追问故障细节，确认后才调用 create_repair_ticket，所以补一句确认
                print(f"① 补充：{CONFIRM}")
                tid, done = run(client, "/api/chat/stream", {"thread_id": tid, "message": CONFIRM}, args.user)
            if not done or done["status"] != "interrupted":
                print("没有停在审批上（模型还在追问），再跑一次")
                return
            approved = args.case == "approve"
            body = {"thread_id": tid, "approved": approved, "reason": "" if approved else "故障描述不够具体，请先和用户确认漏水位置"}
            print(f"② {'批准' if approved else '拒绝'}：POST /api/chat/resume {json.dumps(body, ensure_ascii=False)}")
            run(client, "/api/chat/resume", body, args.user)
            print("③ 再点一次（重复提交）：")
            run(client, "/api/chat/resume", body, args.user)
        else:
            print(f"① 提问：{QUESTION}（看到 tool_started 就断开）")
            tid, _ = run(client, "/api/chat/stream", {"thread_id": None, "message": QUESTION}, args.user, stop_on="tool_started")
            time.sleep(1)
            print("② 同一段对话接着问：")
            run(client, "/api/chat/stream", {"thread_id": tid, "message": "那如果充电座指示灯不亮呢？"}, args.user)


if __name__ == "__main__":
    main()
