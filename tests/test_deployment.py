import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from outputs.formfiller.deployment import DeploymentError, validate_snapshot


class DeploymentValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.source = base / "source-checkout"
        self.root = base / "installed"
        self.source.mkdir()
        (self.root / "formfiller" / "web_static").mkdir(parents=True)
        (self.root / "formfiller" / "__init__.py").write_text("# fixture package\n", encoding="utf-8")
        (self.root / "formfiller" / "web_static" / "index.html").write_text("<main>fixture</main>\n", encoding="utf-8")
        self.manifest = self.root / "install-manifest.json"
        self.write_manifest()

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self):
        files = {}
        for path in sorted((self.root / "formfiller").rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                files[path.relative_to(self.root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.manifest.write_text(json.dumps({"version": 1, "source_root": str(self.source), "files": files}), encoding="utf-8")

    def test_hashes_inventory_and_current_file_are_verified(self):
        current = self.root / "formfiller" / "__init__.py"
        self.assertEqual(validate_snapshot(self.root, current_file=current), {"version": 1, "files": 2})

    def test_modified_file_fails_closed(self):
        (self.root / "formfiller" / "__init__.py").write_text("# changed\n", encoding="utf-8")
        with self.assertRaisesRegex(DeploymentError, "install_hash_mismatch"):
            validate_snapshot(self.root)

    def test_unlisted_package_file_fails_closed(self):
        (self.root / "formfiller" / "extra.py").write_text("# extra\n", encoding="utf-8")
        with self.assertRaisesRegex(DeploymentError, "install_inventory_mismatch"):
            validate_snapshot(self.root)

    def test_unlisted_binary_import_fails_closed(self):
        (self.root / "formfiller" / "extension.pyd").write_bytes(b"fixture binary")
        with self.assertRaisesRegex(DeploymentError, "install_inventory_mismatch"):
            validate_snapshot(self.root)

    def test_package_launcher_script_is_rejected(self):
        (self.root / "formfiller" / "helper.cmd").write_text("echo fixture", encoding="utf-8")
        with self.assertRaisesRegex(DeploymentError, "install_forbidden_file"):
            validate_snapshot(self.root)

    def test_snapshot_may_not_overlap_source_tree(self):
        self.manifest.write_text(json.dumps({"version": 1, "source_root": str(self.root.parent), "files": []}), encoding="utf-8")
        with self.assertRaisesRegex(DeploymentError, "install_source_overlap"):
            validate_snapshot(self.root)


if __name__ == "__main__":
    unittest.main()
