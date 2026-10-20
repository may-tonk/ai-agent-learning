"""
入口 1：审核一张报销单，把 agent 每一步做了什么打印出来。

用法（在项目根目录 E:\\agent学习任务 下，PyCharm Terminal 里看到 (.venv) 再执行）：
    python code/day05-expense-agent/run_review.py --claim C002              # 用 v2 工具审核 C002
    python code/day05-expense-agent/run_review.py --claim C002 --tools v1   # 用 v1（D3 原始版）工具
    python code/day05-expense-agent/run_review.py --claim C002 --show-json  # 额外打印每一轮的原始请求和响应 JSON

完整对话记录会保存到 code/day05-expense-agent/logs/ 下（不进 Git）。
"""
import argparse
import json
from datetime import datetime

import config
from agent import build_system_prompt, build_task, dump_transcript, pretty, run_agent
from tools import get_toolset


def make_printer(show_json):
    """返回一个 on_event 回调：agent 循环每发生一件事，就调用它一次。"""
    def on_event(kind, data):
        step = data.get("step")
        if kind == "request" and show_json:
            print(f"\n----- 第 {step} 轮 请求 JSON -----\n{pretty(data['request'])}")
        elif kind == "response":
            if show_json:
                print(f"\n----- 第 {step} 轮 响应 JSON -----\n{pretty(data['response'])}")
            print(f"\n[第 {step} 轮] finish_reason={data['finish_reason']}  "
                  f"本轮输入 {data['prompt_tokens']} tokens / 输出 {data['completion_tokens']} tokens")
        elif kind == "thought":
            print(f"  思考：{data['text'].strip()}")
        elif kind == "tool":
            flag = "  ✗ 出错" if data["is_error"] else ""
            print(f"  调用 {data['name']}({data['args'][:150]}){flag}")
            print(f"    → {data['output'][:200].replace(chr(10), ' ')}{'…' if len(data['output']) > 200 else ''}")
        elif kind == "nudge":
            print("  （模型没有调用 review_submit，提醒它一次）")
    return on_event


def review(claim_id, tools_name, show_json=False, client=None):
    toolset, data_access = get_toolset(tools_name)
    client = client or config.get_openai_client(strict=toolset.strict)
    run = run_agent(client, config.MODEL, build_system_prompt(data_access), build_task(claim_id), toolset,
                    extra_body=config.EXTRA_BODY, on_event=make_printer(show_json))

    config.LOGS_DIR.mkdir(exist_ok=True)
    log_file = config.LOGS_DIR / f"review_{claim_id}_{tools_name}_{datetime.now():%Y%m%d_%H%M%S}.json"
    log_file.write_text(json.dumps(dump_transcript(run), ensure_ascii=False, indent=2), encoding="utf-8")
    return run, log_file


def main():
    parser = argparse.ArgumentParser(description="审核一张报销单")
    parser.add_argument("--claim", default="C002", help="报销单号，例如 C002")
    parser.add_argument("--tools", default="v2", choices=["v1", "v2"], help="用哪一版工具")
    parser.add_argument("--show-json", action="store_true", help="打印每一轮原始请求和响应 JSON")
    args = parser.parse_args()

    print(f"模型 {config.MODEL}｜接口 {config.BASE_URL}｜工具 {args.tools}｜报销单 {args.claim}")
    run, log_file = review(args.claim, args.tools, args.show_json)

    print("\n" + "=" * 60)
    print(f"结束原因：{run.stop_reason}｜模型调用 {run.steps} 次｜工具调用 {run.tool_calls} 次（出错 {run.tool_errors} 次）"
          f"｜并行调用 {run.parallel_batches} 次｜累计输入 {run.prompt_tokens} / 输出 {run.completion_tokens} tokens")
    if run.result:
        r = run.result
        print(f"结论：{r.decision}｜申请 {r.requested_total}｜核定 {r.approved_total}")
        for it in r.items:
            print(f"  {it.item_id}  {it.status:<8} {it.requested_amount:>8.2f} → {it.approved_amount:>8.2f}  "
                  f"{','.join(it.policy_refs) or '-':<10} {it.reason}")
        print(f"总结：{r.summary}")
    print(f"完整记录：{log_file}")


if __name__ == "__main__":
    main()
