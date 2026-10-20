"""审核结果结构的校验，以及评测数据本身的正确性（标准答案写错了，评测就没有意义）。"""
import json
import unittest

from pydantic import ValidationError

import config
from schemas.review import ReviewResult


def c002_result(**overrides):
    """C002 的标准答案：上海住宿核减，其余通过。"""
    items = [
        ("C002-01", "approved", 1150, 1150), ("C002-02", "adjusted", 2340, 1800), ("C002-03", "approved", 180, 180),
        ("C002-04", "approved", 260, 260), ("C002-05", "approved", 95, 95), ("C002-06", "approved", 85, 85),
        ("C002-07", "approved", 1150, 1150),
    ]
    data = {"claim_id": "C002", "decision": "partial", "requested_total": 5260, "approved_total": 4720,
            "items": [{"item_id": i, "status": s, "requested_amount": r, "approved_amount": a,
                       "policy_refs": [], "reason": "-"} for i, s, r, a in items],
            "summary": "-"}
    data.update(overrides)
    return data


class ReviewResultTest(unittest.TestCase):
    def test_valid(self):
        ReviewResult.model_validate(c002_result())

    def test_wrong_total_is_rejected_with_hint(self):
        with self.assertRaises(ValidationError) as cm:
            ReviewResult.model_validate(c002_result(approved_total=4700))
        self.assertIn("4720.00", str(cm.exception))

    def test_decision_must_follow_p62(self):
        with self.assertRaises(ValidationError) as cm:
            ReviewResult.model_validate(c002_result(decision="approve"))
        self.assertIn("partial", str(cm.exception))

    def test_rejected_item_must_be_zero(self):
        data = c002_result()
        data["items"][0].update(status="rejected")
        with self.assertRaises(ValidationError):
            ReviewResult.model_validate(data)


class EvalDataTest(unittest.TestCase):
    def test_requested_totals_match_claim_files(self):
        cases = json.loads(config.EVAL_FILE.read_text(encoding="utf-8"))
        self.assertEqual(len(cases), len(list(config.CLAIMS_DIR.glob("*.json"))))
        for case in cases:
            claim = json.loads((config.CLAIMS_DIR / f"{case['claim_id']}.json").read_text(encoding="utf-8"))
            self.assertAlmostEqual(sum(i["amount"] for i in claim["items"]), case["requested_total"], places=2)
            self.assertLessEqual(case["expected_approved_total"], case["requested_total"])


if __name__ == "__main__":
    unittest.main()
