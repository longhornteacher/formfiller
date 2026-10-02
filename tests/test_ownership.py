import tempfile
import unittest
from pathlib import Path

from outputs.formfiller.ownership import RuntimeOwnerError, bind_runtime, verify_runtime_owner


class RuntimeOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.runtime = self.root / "runtime"

    def tearDown(self):
        self.temp.cleanup()

    def test_unpaired_workspace_fails_closed(self):
        with self.assertRaisesRegex(RuntimeOwnerError, "runtime_owner_missing"):
            verify_runtime_owner(self.workspace, self.runtime)

    def test_bind_and_verify_pair(self):
        owner = bind_runtime(self.workspace, self.runtime)
        self.assertEqual(len(owner), 32)
        verify_runtime_owner(self.workspace, self.runtime)
        with self.assertRaisesRegex(RuntimeOwnerError, "runtime_owner_exists"):
            bind_runtime(self.workspace, self.runtime)

    def test_mismatched_pair_is_never_repaired_automatically(self):
        bind_runtime(self.workspace, self.runtime)
        (self.runtime / ".formfiller-owner.json").write_text('{"owner_id":"' + "0" * 32 + '"}')
        with self.assertRaisesRegex(RuntimeOwnerError, "runtime_owner_mismatch"):
            verify_runtime_owner(self.workspace, self.runtime)


if __name__ == "__main__":
    unittest.main()
