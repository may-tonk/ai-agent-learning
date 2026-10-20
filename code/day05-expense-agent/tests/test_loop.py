"""agent 循环的测试：用假模型按剧本走，验证循环在各种情况下的行为。"""
import unittest

from agent import build_system_prompt, build_task, run_agent
from tests.fakes import FakeClient, make_response
from tests.test_review_and_data import c002_result
from tools import get_toolset


def run(responses, toolset_name="v2", **kw):
    toolset, data_access = get_toolset(toolset_name)
    client = FakeClient(responses)
    result = run_agent(client, "fake-model", build_system_prompt(data_access), build_task("C002"), toolset, **kw)
    return result, client


class LoopTest(unittest.TestCase):
    def test_parallel_calls_then_bad_submit_then_good_submit(self):
        wrong = c002_result(approved_total=4700)          # 第一次提交故意算错
        responses = [
            make_response("先读取报销单。", [("c1", "claims_get", {"claim_id": "C002", "response_format": "concise"})]),
            # 一次请求两个工具 = 并行调用
            make_response("查住宿条款并计算晚数。", [
                ("c2", "policy_search", {"query": "住宿 标准", "max_results": None}),
                ("c3", "calc_days_between", {"start_date": "2026-09-22", "end_date": "2026-09-25"})]),
            make_response(None, [("c4", "review_submit", wrong)]),
            make_response("修正总额后重新提交。", [("c5", "review_submit", c002_result())]),
        ]
        result, client = run(responses)
        self.assertEqual(result.stop_reason, "submitted")
        self.assertEqual(result.result.approved_total, 4720)
        self.assertEqual(result.steps, 4)
        self.assertEqual(result.tool_calls, 5)
        self.assertEqual(result.tool_errors, 1)          # 第一次提交被校验拦下
        self.assertEqual(result.parallel_batches, 1)
        self.assertEqual(result.prompt_tokens, 400)

        # 第 3 次请求里：并行的两个工具各有一条 role=tool 的结果，tool_call_id 一一对应
        third = client.requests[2]["messages"]
        tool_msgs = [m for m in third if m["role"] == "tool"]
        self.assertEqual([m["tool_call_id"] for m in tool_msgs], ["c1", "c2", "c3"])
        # 第 4 次请求里：校验错误作为工具结果交还给模型
        self.assertIn("4720.00", client.requests[3]["messages"][-1]["content"])

    def test_text_only_reply_gets_one_nudge(self):
        responses = [make_response("看起来没问题。"), make_response("确实没问题。")]
        result, client = run(responses)
        self.assertEqual(result.stop_reason, "no_submit")
        self.assertIn("review_submit", client.requests[1]["messages"][-1]["content"])

    def test_max_steps(self):
        call = ("c", "calc_evaluate", {"expression": "1+1"})
        result, _ = run([make_response(None, [call]) for _ in range(3)], max_steps=3)
        self.assertEqual(result.stop_reason, "max_steps")
        self.assertIsNone(result.result)

    def test_v1_uses_plain_paths(self):
        responses = [
            make_response(None, [("c1", "read_file", {"path": "data/claims/C002.json"})]),
            make_response(None, [("c2", "review_submit", c002_result())]),
        ]
        result, client = run(responses, toolset_name="v1")
        self.assertEqual(result.stop_reason, "submitted")
        self.assertIn("data/claims", client.requests[0]["messages"][0]["content"])   # v1 的提示词里告诉了路径
        self.assertNotIn("strict", client.requests[0]["tools"][0]["function"])


if __name__ == "__main__":
    unittest.main()
