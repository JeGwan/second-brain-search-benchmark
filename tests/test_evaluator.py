import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import evaluator  # noqa: E402


class TestNormalize(unittest.TestCase):
    def test_strips_thousands_comma_between_digits(self):
        self.assertEqual(evaluator.normalize("$500,000"), "$500000")

    def test_lowercases_and_collapses_whitespace(self):
        self.assertEqual(evaluator.normalize("TX-9921\n  done"), "tx-9921 done")

    def test_nfkc_fullwidth_to_halfwidth(self):
        # 전각 숫자 ５０ → 반각 50
        self.assertEqual(evaluator.normalize("５０만"), "50만")

    def test_empty_and_none(self):
        self.assertEqual(evaluator.normalize(""), "")
        self.assertEqual(evaluator.normalize(None), "")


class TestKeyfactCoverage(unittest.TestCase):
    KF = [
        {"label": "송금 액수", "aliases": ["$500,000", "50만 달러", "500000"]},
        {"label": "승인 번호", "aliases": ["TX-9921", "TX9921"]},
    ]

    def test_full_coverage_with_alias_and_normalization(self):
        ctx = "6월 14일 $500,000 거래, 결재 번호 TX-9921 처리됨."
        cov, facts = evaluator.compute_keyfact_coverage(ctx, self.KF)
        self.assertEqual(cov, 1.0)
        self.assertTrue(all(f["found"] for f in facts))

    def test_partial_coverage(self):
        ctx = "송금액은 50만 달러였다."  # 승인 번호 없음
        cov, facts = evaluator.compute_keyfact_coverage(ctx, self.KF)
        self.assertEqual(cov, 0.5)
        self.assertIsNone([f for f in facts if f["label"] == "승인 번호"][0]["matched_alias"])

    def test_empty_key_facts(self):
        cov, facts = evaluator.compute_keyfact_coverage("아무 텍스트", [])
        self.assertIsNone(cov)
        self.assertEqual(facts, [])


class TestSemanticConsistency(unittest.TestCase):
    def test_perfect_consistency(self):
        c = evaluator.compute_semantic_consistency({"a", "b"}, [{"a", "b"}, {"a", "b"}])
        self.assertEqual(c, 1.0)

    def test_partial_loss_averaged(self):
        # 변형1: a,b 모두 / 변형2: a만 → (1.0 + 0.5)/2
        c = evaluator.compute_semantic_consistency({"a", "b"}, [{"a", "b"}, {"a"}])
        self.assertAlmostEqual(c, 0.75)

    def test_empty_original_is_full(self):
        self.assertEqual(evaluator.compute_semantic_consistency(set(), [set(), {"x"}]), 1.0)

    def test_no_paraphrases_returns_none(self):
        self.assertIsNone(evaluator.compute_semantic_consistency({"a"}, []))


class TestQuestionsSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.path.join(os.path.dirname(__file__), "..", "questions.json")
        with open(path, encoding="utf-8") as f:
            cls.qs = json.load(f)

    def test_every_question_has_key_facts(self):
        for q in self.qs:
            self.assertIn("key_facts", q, q["id"])
            self.assertTrue(q["key_facts"], q["id"])
            for kf in q["key_facts"]:
                self.assertIn("label", kf)
                self.assertTrue(kf.get("aliases"), f"{q['id']} {kf.get('label')}")

    def test_no_legacy_rubric(self):
        for q in self.qs:
            self.assertNotIn("evaluation_rubric", q, q["id"])


class TestSummarize(unittest.TestCase):
    def test_micro_average_and_axis(self):
        results = [
            {"axis": "A", "n_facts": 2, "n_found": 2, "retrieval_recall": 1.0,
             "semantic_consistency": 1.0},
            {"axis": "A", "n_facts": 2, "n_found": 1, "retrieval_recall": 0.5,
             "semantic_consistency": 0.5},
            {"axis": "B", "n_facts": 1, "n_found": 0, "retrieval_recall": 0.0,
             "semantic_consistency": None},
        ]
        s = evaluator.summarize(results)
        self.assertEqual(s["total_facts"], 5)
        self.assertEqual(s["total_found"], 3)
        self.assertAlmostEqual(s["micro_coverage"], 3 / 5)
        self.assertAlmostEqual(s["avg_retrieval_recall"], (1.0 + 0.5 + 0.0) / 3)
        self.assertAlmostEqual(s["avg_semantic_consistency"], (1.0 + 0.5) / 2)
        self.assertEqual(s["axis_scores"]["A"], {"found": 3, "facts": 4})


if __name__ == "__main__":
    unittest.main()
