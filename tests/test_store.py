import json
import tempfile
import unittest
from pathlib import Path

from outputs.formfiller.store import FormStore, FormStoreError
from outputs.formfiller import web
from outputs.formfiller.store import template_fingerprint


class FormStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Path(self.temp.name)
        self.forms = [
            {"alias": "F01", "url": "https://forms.office.com/r?id=synthetic-old",
             "schema": {"questions": []}, "answers": []},
            {"alias": "F02", "url": "https://forms.office.com/r?id=synthetic-second",
             "schema": {"questions": []}, "answers": []},
        ]
        (self.config / "forms.json").write_text(json.dumps({"forms": self.forms}), encoding="utf-8")
        self.store = FormStore(self.config)

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_ids_are_stable_and_private_data_is_not_listed(self):
        self.assertEqual([row["id"] for row in self.store.list_forms()], ["F01", "F02"])
        self.assertEqual(self.store.get_form("F01")["alias"], "F01")
        self.assertNotIn("url", self.store.list_forms()[0])

    def test_create_update_and_archive_keep_immutable_safe_id(self):
        created = self.store.create_form("Morning form", {"url": "https://forms.office.com/r?id=synthetic-new"})
        form = self.store.get_form(created["id"])
        self.assertEqual(form["id"], created["id"])
        self.assertIsNone(form["schema"])
        updated = self.store.update_form(created["id"], {"schema": {"questions": []}, "answers": []})
        self.assertEqual(updated["id"], created["id"])
        self.store.archive_form(created["id"])
        self.assertNotIn(created["id"], [row["id"] for row in self.store.list_forms()])
        with self.assertRaises(FormStoreError):
            self.store.get_form(created["id"])
        self.assertIn(created["id"], [row.get("id", row.get("alias")) for row in json.loads((self.config / "forms.json").read_text())["forms"]])

    def test_duplicate_url_is_rejected_even_after_archive(self):
        self.store.archive_form("F01")
        with self.assertRaisesRegex(FormStoreError, "duplicate_form_url"):
            self.store.create_form("Duplicate", {"url": self.forms[0]["url"]})

    def test_form_id_cannot_be_reassigned(self):
        with self.assertRaises(FormStoreError):
            self.store.update_form("F01", {"id": "new-id"})

    def record_example(self):
        schema = web.sample_schema()
        self.store.update_form('F01', {'schema': schema, 'answers': [
            {'kind': 'text', 'value': 'Submitted example'}, {'kind': 'radio', 'values': ['Option B']}, {'kind': 'date'}]})
        form = self.store.get_form('F01')
        self.store.record_submission('F01', form, '2026-10-21', template_fingerprint(form))
        return form

    def test_confirmed_contents_persist_without_changing_approval_fingerprint(self):
        original = self.record_example()
        saved = FormStore(self.config).get_form('F01')
        self.assertEqual(template_fingerprint(saved), template_fingerprint(original))
        self.assertEqual(saved['last_submission']['date'], '2026-10-21')
        self.assertEqual(saved['last_submission']['answers'][2], {'kind': 'date', 'value': '10/21/2026'})
        seed, source = self.store.submission_seed(saved)
        self.assertEqual(source, 'last_submission')
        self.assertEqual(web.normalized_answers(seed['answers']), web.normalized_answers(original['answers']))
        self.assertNotIn('last_submission', self.store.list_forms()[0])

    def test_saved_edits_override_last_submission_but_do_not_erase_it(self):
        original = self.record_example()
        answers = original['answers']
        answers[0]['value'] = 'Unsubmitted example edit'
        self.store.update_form('F01', {'answers': answers})
        saved = self.store.get_form('F01')
        seed, source = self.store.submission_seed(saved)
        self.assertEqual(source, 'saved_changes')
        self.assertEqual(seed['answers'][0]['value'], 'Unsubmitted example edit')
        self.assertEqual(saved['last_submission']['answers'][0]['value'], 'Submitted example')

    def test_url_change_cannot_reuse_another_forms_last_submission(self):
        self.record_example()
        self.store.update_form('F01', {'url': 'https://forms.office.com/r?id=synthetic-other-target'})
        self.assertEqual(self.store.submission_seed(self.store.get_form('F01'))[1], 'saved_changes')

    def test_last_submission_cannot_be_set_through_form_crud_or_replaced_by_older_date(self):
        form = self.record_example()
        with self.assertRaises(FormStoreError):
            self.store.update_form('F01', {'last_submission': {'date': '2026-10-20'}})
        with self.assertRaises(FormStoreError):
            self.store.record_submission('F01', form, '2026-10-20', template_fingerprint(form))
        self.assertEqual(self.store.get_form('F01')['last_submission']['date'], '2026-10-21')


if __name__ == "__main__":
    unittest.main()
