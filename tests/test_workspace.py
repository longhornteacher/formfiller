import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from outputs.formfiller.workspace import WorkspaceError, resolve_workspace


class WorkspaceResolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.local = Path(self.temp.name) / "local"
        (self.local / "FormFiller").mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def env(self):
        return patch.dict(os.environ, {"LOCALAPPDATA": str(self.local)}, clear=True)

    def test_no_locator_keeps_legacy_paths(self):
        with self.env():
            paths = resolve_workspace(self.root)
        self.assertEqual(paths.config_dir, self.root / "config")
        self.assertEqual(paths.state_dir, self.root / "state")
        self.assertFalse(paths.external_runtime)

    def test_valid_locator_resolves_private_workspace_runtime_and_app(self):
        workspace = Path(self.temp.name) / "private"
        runtime = Path(self.temp.name) / "runtime"
        installed = Path(self.temp.name) / "installed"
        (self.local / "FormFiller" / "paths.json").write_text(json.dumps({
            "workspace": str(workspace), "runtime": str(runtime), "installed_app": str(installed),
        }), encoding="utf-8")
        with self.env():
            paths = resolve_workspace(self.root)
        self.assertEqual(paths.config_dir, workspace / "config")
        self.assertEqual(paths.state_dir, runtime / "state")
        self.assertEqual(paths.profile_dir, runtime / "browser-profile")
        self.assertEqual(paths.installed_app, installed)
        self.assertTrue(paths.external_workspace and paths.external_runtime)

    def test_bad_locator_never_falls_back_to_legacy_paths(self):
        locator = self.local / "FormFiller" / "paths.json"
        locator.write_text('{"workspace": "relative", "runtime": "relative"}', encoding="utf-8")
        with self.env(), self.assertRaisesRegex(WorkspaceError, "workspace_locator_invalid"):
            resolve_workspace(self.root)


if __name__ == "__main__":
    unittest.main()
