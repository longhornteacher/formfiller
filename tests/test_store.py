import json
import tempfile
import unittest
from pathlib import Path

from outputs.formfiller.store import FormStore, FormStoreError


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


if __name__ == "__main__":
    unittest.main()
