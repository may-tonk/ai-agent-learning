"""
入口 2：评测。用同一批报销单（data/eval_cases.json，每张都有人工标注的标准答案）分别跑 v1 和 v2，
比较准确率、工具调用次数、token 消耗。

这就是《Writing effective tools for agents》里说的方法：工具好不好，不靠感觉，靠评测数据。
真实团队改提示词、改工具、换模型之前和之后都会跑一遍评测，确认"改好了"而不是"改得不一样了"。

用法：
    python code/day05-expense-agent/run_eval.py                        # v1 和 v2 各跑全部 8 张
    python code/day05-expense-agent/run_eval.py --tools v2             # 只跑 v2
    python code/day05-expense-agent/run_eval.py --claims C002 C007     # 只跑指定的报销单

费用：每张报销单大约 5~15 轮调用，全部跑完是几十万 tokens 的量级，按 DeepSeek 价格大约几毛钱。
"""
import argparse
import json
from datetime import datetime

import config
from agent import build_system_prompt, build_task, dump_transcript, run_agent
from schemas.review import TOLERANCE
from tools import get_toolset


def grade(case, run):
    """对照标准答案打分：结论和核定总额都对，才算这一张审对了。"""
    r = run.result
    if r is None:
        return {"decision_ok": False, "amount_ok": False, "correct": False,
                "got": f"未提交（{run.stop_reason}）"}
    decision_ok = r.decision == case["expected_decision"]
    amount_ok = abs(r.approved_total - case["expected_approved_total"]) <= TOLERANCE
    return {"decision_ok": decision_ok, "amount_ok": amount_ok, "correct": decision_ok and amount_ok,
            "got": f"{r.decision} {r.approved_total}"}


def evaluate(tools_name, cases, client=None):
    toolset, data_access = get_toolset(tools_name)
    client = client or config.get_openai_client(strict=toolset.strict)
    system_prompt = build_system_prompt(data_access)
    rows = []
    for case in cases:
        print(f"  [{tools_name}] 审核 {case['claim_id']} ...", end="", flush=True)
        try:
            run = run_agent(client, config.MODEL, system_prompt, build_task(case["claim_id"]), toolset,
                            extra_body=config.EXTRA_BODY)
        except Exception as e:      # 网络错误等：记一笔失败，不要让整个评测中断
            print(f" 调用失败：{type(e).__name__}: {e}")
            rows.append({"claim_id": case["claim_id"], "correct": False, "got": f"异常 {type(e).__name__}",
                         "expected": f"{case['expected_decision']} {case['expected_approved_total']}", "stats": {}})
            continue
        g = grade(case, run)
        print(f" {'✓' if g['correct'] else '✗'}  得到 {g['got']}｜标准 {case['expected_decision']} {case['expected_approved_total']}")
        rows.append({"claim_id": case["claim_id"], **g,
                     "expected": f"{case['expected_decision']} {case['expected_approved_total']}",
                     "stats": run.stats(), "transcript": dump_transcript(run)})
    return rows


def summarize(rows):
    n = len(rows)
    ok = [r for r in rows if r["stats"]]
    avg = lambda key: sum(r["stats"][key] for r in ok) / len(ok) if ok else 0
    return {
        "cases": n,
        "accuracy": sum(r["correct"] for r in rows) / n if n else 0,
        "decision_accuracy": sum(r.get("decision_ok", False) for r in rows) / n if n else 0,
        "avg_steps": avg("steps"),
        "avg_tool_calls": avg("tool_calls"),
        "avg_tool_errors": avg("tool_errors"),
        "avg_prompt_tokens": avg("prompt_tokens"),
        "avg_completion_tokens": avg("completion_tokens"),
    }


def main():
    parser = argparse.ArgumentParser(description="评测 v1 / v2 工具")
    parser.add_argument("--tools", nargs="+", default=["v1", "v2"], choices=["v1", "v2"])
    parser.add_argument("--claims", nargs="+", help="只评测这些报销单，默认全部")
    args = parser.parse_args()

    cases = json.loads(config.EVAL_FILE.read_text(encoding="utf-8"))
    if args.claims:
        cases = [c for c in cases if c["claim_id"] in args.claims]

    results = {}
    for name in args.tools:
        print(f"\n===== 工具集 {name} =====")
        rows = evaluate(name, cases)
        results[name] = {"summary": summarize(rows), "rows": rows}

    print("\n" + "=" * 72)
    print(f"{'指标':<22}" + "".join(f"{n:>14}" for n in results))
    labels = [("accuracy", "完全正确率", "{:.0%}"), ("decision_accuracy", "结论正确率", "{:.0%}"),
              ("avg_steps", "平均模型调用次数", "{:.1f}"), ("avg_tool_calls", "平均工具调用次数", "{:.1f}"),
              ("avg_tool_errors", "平均工具出错次数", "{:.1f}"), ("avg_prompt_tokens", "平均输入 tokens", "{:.0f}"),
              ("avg_completion_tokens", "平均输出 tokens", "{:.0f}")]
    for key, label, fmt in labels:
        print(f"{label:<18}" + "".join(f"{fmt.format(results[n]['summary'][key]):>14}" for n in results))
    print("\n逐张结果：")
    for name in results:
        wrong = [r for r in results[name]["rows"] if not r["correct"]]
        if not wrong:
            print(f"  {name}：全部正确")
        for r in wrong:
            print(f"  {name}：{r['claim_id']} 得到 {r['got']}，应为 {r['expected']}")

    config.LOGS_DIR.mkdir(exist_ok=True)
    out = config.LOGS_DIR / f"eval_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n详细结果（含每张报销单的完整对话）：{out}")


if __name__ == "__main__":
    main()
