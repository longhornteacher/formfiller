from copy import deepcopy
from datetime import date
import unittest

from outputs.formfiller.browser import answer_plan, BrowserError
from outputs.formfiller.schema_changes import reconcile
from test_browser import FORM


class SchemaChangeTests(unittest.TestCase):
    def setUp(self):
        self.form = deepcopy(FORM)
        self.observed = deepcopy(FORM["schema"])
        self.day = date(2026, 10, 21)

    def test_added_unused_choice_keeps_reviewed_answer(self):
        controls = self.observed["questions"][2]["controls"]
        controls.append({**controls[0], "label": "New option"})
        effective, changed = reconcile(self.form, self.observed, self.day)
        self.assertTrue(changed)
        self.assertEqual(answer_plan(effective, self.day)[2], [True, False, False])
        self.assertEqual(self.form, FORM)

    def test_removed_unselected_choice_is_ignored(self):
        self.observed["questions"][2]["controls"].pop()
        effective, _ = reconcile(self.form, self.observed, self.day)
        self.assertEqual(answer_plan(effective, self.day)[2], [True])

    def test_removed_selected_required_choice_needs_review(self):
        self.observed["questions"][2]["controls"].pop(0)
        with self.assertRaises(BrowserError):
            reconcile(self.form, self.observed, self.day)

    def test_reorder_and_remove_question_match_by_title(self):
        self.observed["questions"] = list(reversed(self.observed["questions"][1:]))
        effective, _ = reconcile(self.form, self.observed, self.day)
        self.assertEqual(effective["answers"], list(reversed(self.form["answers"][1:])))

    def test_optional_new_question_is_blank(self):
        self.observed["questions"].append({"title": "Optional new question", "required": False,
            "controls": [{"kind": "text", "label": "Optional", "matrix": False, "placeholder": ""}]})
        effective, _ = reconcile(self.form, self.observed, self.day)
        self.assertEqual(answer_plan(effective, self.day)[-1], [""])

    def test_required_new_question_blocks(self):
        self.observed["questions"].append({"title": "Required new question", "required": True, "controls": []})
        with self.assertRaises(BrowserError):
            reconcile(self.form, self.observed, self.day)

    def test_optional_dropped_selected_item_is_blank(self):
        self.form["schema"]["questions"][2]["required"] = False
        self.observed["questions"][2]["required"] = False
        self.observed["questions"][2]["controls"].pop(0)
        effective, _ = reconcile(self.form, self.observed, self.day)
        self.assertEqual(answer_plan(effective, self.day)[2], [False])

    def test_duplicate_titles_and_type_changes_block(self):
        self.observed["questions"][0]["title"] = self.observed["questions"][1]["title"]
        with self.assertRaises(BrowserError):
            reconcile(self.form, self.observed, self.day)
        self.observed = deepcopy(self.form["schema"])
        self.observed["questions"][1]["controls"][0]["kind"] = "radio"
        with self.assertRaises(BrowserError):
            reconcile(self.form, self.observed, self.day)
