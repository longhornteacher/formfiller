import unittest
from datetime import date

from outputs.formfiller.browser import BrowserError, answer_plan


class AnswerPlanSafetyTests(unittest.TestCase):
    def test_malformed_schema_and_answer_shapes_fail_with_sanitized_code(self):
        cases = [
            None,
            {"schema": None, "answers": []},
            {"schema": {"questions": [None]}, "answers": [{}]},
            {"schema": {"questions": [{"controls": [None]}]}, "answers": [{}]},
            {"schema": {"questions": [{}]}, "answers": [None]},
        ]
        for form in cases:
            with self.subTest(form_type=type(form).__name__):
                with self.assertRaises(BrowserError) as caught:
                    answer_plan(form, date(2026, 10, 1))
                self.assertEqual(caught.exception.code, "ANSWER_CONFIG_INVALID")


if __name__ == "__main__":
    unittest.main()
