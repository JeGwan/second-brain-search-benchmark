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


if __name__ == "__main__":
    unittest.main()
