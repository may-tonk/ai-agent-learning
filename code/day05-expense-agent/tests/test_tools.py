"""工具层的单元测试：不调用模型，直接测工具函数和 Toolset.execute。"""
import json
import unittest

from tools import get_toolset
from tools.calculator import safe_eval


class CalculatorTest(unittest.TestCase):
    def test_basic_and_functions(self):
        self.assertEqual(safe_eval("3*600"), 1800)
        self.assertEqual(safe_eval("sum([1150, 1800, 535, 85, 1150])"), 4720)
        self.assertEqual(safe_eval("min(410, 2*150)"), 300)
        self.assertEqual(safe_eval("（2340－1800）×2"), 1080)     # 中文符号会被自动规范化

    def test_rejects_code(self):
        for bad in ("__import__('os').system('dir')", "open('x')", "a+1", "2**100"):
            with self.assertRaises((ValueError, SyntaxError)):
                safe_eval(bad)

    def test_tool_errors_are_actionable(self):
        toolset, _ = get_toolset("v2")
        out, err = toolset.execute("calc_evaluate", '{"expression": "1,150 + 2"}')
        self.assertTrue(err)
        self.assertIn("正确示例", out)

    def test_days_between(self):
        toolset, _ = get_toolset("v2")
        out, err = toolset.execute("calc_days_between", {"start_date": "2026-09-22", "end_date": "2026-09-25"})
        self.assertFalse(err)
        self.assertEqual(json.loads(out)["days"], 3)


class ClaimsAndPolicyTest(unittest.TestCase):
    def setUp(self):
        self.v2, _ = get_toolset("v2")

    def test_concise_is_much_smaller_than_detailed(self):
        concise, _ = self.v2.execute("claims_get", {"claim_id": "C002", "response_format": "concise"})
        detailed, _ = self.v2.execute("claims_get", {"claim_id": "C002", "response_format": "detailed"})
        data = json.loads(concise)
        self.assertEqual(data["requested_total"], 5260.0)
        self.assertNotIn("invoice", data["items"][0])
        self.assertLess(len(concise), len(detailed) / 2)

    def test_unknown_claim_lists_existing_ids(self):
        out, err = self.v2.execute("claims_get", {"claim_id": "C099", "response_format": "concise"})
        self.assertTrue(err)
        self.assertIn("C001", out)

    def test_bad_args_are_explained(self):
        out, err = self.v2.execute("claims_get", '{"claim_id": "2"}')
        self.assertTrue(err)
        self.assertIn("claim_id", out)
        self.assertIn("response_format", out)

    def test_policy_search(self):
        out, err = self.v2.execute("policy_search", {"query": "住宿 标准", "max_results": None})
        self.assertFalse(err)
        self.assertIn("P2", out)
        out, _ = self.v2.execute("policy_search", {"query": "一线城市住宿上限", "max_results": 1})  # 长词走两字切分
        self.assertIn("P2.1", out)
        out, _ = self.v2.execute("policy_search", {"query": "P4", "max_results": None})
        self.assertIn("P4.2", out)
        out, err = self.v2.execute("policy_search", {"query": "股票期权", "max_results": None})
        self.assertTrue(err)
        self.assertIn("制度目录", out)


class V1Test(unittest.TestCase):
    def test_v1_silently_truncates_like_day7(self):
        v1, _ = get_toolset("v1")
        out, err = v1.execute("read_file", {"path": "data/claims/C002.json"})
        self.assertFalse(err)
        self.assertEqual(len(out), 5000)        # 原文件更长，但模型不知道被截断了
        self.assertNotIn("截断", out)

    def test_v1_cannot_escape_data_dir(self):
        v1, _ = get_toolset("v1")
        out, err = v1.execute("read_file", {"path": "../../../.env"})
        self.assertTrue(err)


class StrictSchemaTest(unittest.TestCase):
    def test_all_v2_schemas_are_strict_compatible(self):
        v2, _ = get_toolset("v2")

        def check(node, where):
            if isinstance(node, dict):
                self.assertNotIn("$ref", node, where)
                if node.get("type") == "object":
                    self.assertEqual(sorted(node["required"]), sorted(node["properties"]), where)
                    self.assertIs(node["additionalProperties"], False, where)
                for k, v in node.items():
                    check(v, f"{where}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    check(v, f"{where}[{i}]")

        for tool in v2.openai_tools():
            self.assertTrue(tool["function"]["strict"])
            check(tool["function"]["parameters"], tool["function"]["name"])

    def test_same_tool_two_protocol_formats(self):
        v2, _ = get_toolset("v2")
        o, a = v2.openai_tools()[0], v2.anthropic_tools()[0]
        self.assertEqual(o["function"]["name"], a["name"])
        self.assertEqual(o["function"]["parameters"], a["input_schema"])


if __name__ == "__main__":
    unittest.main()
