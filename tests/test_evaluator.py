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


if __name__ == "__main__":
    unittest.main()
