"""Privacy checks for the allowlisted development package."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "tools" / "Build-CleanSource.ps1"


def source_allowlist() -> list[str]:
    script = BUILDER.read_text(encoding="utf-8")
    match = re.search(r"\$sourceNames\s*=\s*@\((.*?)\)", script, re.S)
    if not match:
        raise AssertionError("Builder has no explicit source allowlist")
    return re.findall(r"'([a-z_]+\.py)'", match.group(1))


class CleanSourcePackagingTests(unittest.TestCase):
    def test_allowlist_covers_every_application_python_module(self) -> None:
        names = source_allowlist()
        self.assertEqual(len(names), len(set(names)), "source allowlist contains duplicates")
        package_modules = {
            path.name for path in (ROOT / "outputs" / "formfiller").glob("*.py")
        }
        self.assertEqual(package_modules - set(names), set(), "new modules must be explicitly packaged")
        self.assertEqual(set(names) - package_modules, set(), "remove stale package names")

    def test_builder_exports_only_synthetic_allowlisted_inputs(self) -> None:
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            self.skipTest("PowerShell is required to exercise the Windows package builder")
        with tempfile.TemporaryDirectory(prefix="formfiller-clean-source-test-") as temporary:
            base = Path(temporary)
            fake_repo = base / "source"
            fake_package = fake_repo / "outputs" / "formfiller"
            fake_package.mkdir(parents=True)
            (fake_package / "web_static" / "nested").mkdir(parents=True)
            for module in source_allowlist():
                (fake_package / module).write_text(f"# synthetic module: {module}\n", encoding="utf-8")
            (fake_package / "web.py").write_text(
                "import argparse, json\n"
                "parser = argparse.ArgumentParser()\n"
                "parser.add_argument('--private', action='store_true')\n"
                "parser.add_argument('--open', action='store_true')\n"
                "parser.add_argument('--workspace')\n"
                "parser.add_argument('--runtime')\n"
                "print(json.dumps(vars(parser.parse_args())))\n", encoding="utf-8")
            (fake_package / "web_static" / "index.html").write_text("synthetic page", encoding="utf-8")
            (fake_package / "web_static" / "nested" / "app.js").write_text("synthetic script", encoding="utf-8")
            (fake_package / "web_static" / "ui_smoke.py").write_text("SYNTHETIC_TEST_ONLY", encoding="utf-8")
            (fake_repo / "outputs" / "requirements.txt").write_text("synthetic-dependency==1\n", encoding="utf-8")

            # These canaries are synthetic and ensure the export's allowlist does not widen.
            private_canary = "SYNTHETIC_PRIVATE_DATA_CANARY"
            for relative in (
                "outputs/config/forms.json",
                "outputs/config/calendar.json",
                "outputs/state/records.json",
                "outputs/reports/run.txt",
                "outputs/.venv/Scripts/python.exe",
                "Accommodation Log.txt",
                "private-workspace/unrelated.json",
            ):
                path = fake_repo / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(private_canary, encoding="utf-8")

            artifacts = base / "artifacts"
            result = subprocess.run(
                [shell, "-NoProfile", "-File", str(BUILDER),
                 "-RepositoryRoot", str(fake_repo), "-OutputRoot", str(artifacts)],
                capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            bundle = artifacts / "formfiller-clean-source"
            expected = {f"formfiller/{name}" for name in source_allowlist()} | {
                "formfiller/web_static/index.html",
                "formfiller/web_static/nested/app.js",
                "requirements.txt",
                "README.txt",
            }
            actual = {path.relative_to(bundle).as_posix() for path in bundle.rglob("*") if path.is_file()}
            self.assertEqual(actual, expected)
            exported = "\n".join(path.read_text(encoding="utf-8") for path in bundle.rglob("*") if path.is_file())
            self.assertNotIn(private_canary, exported)
            sandbox = (artifacts / "FormFiller-Development.wsb").read_text(encoding="utf-8-sig")
            self.assertIn("<Networking>Disable</Networking>", sandbox)
            self.assertIn("<ReadOnly>true</ReadOnly>", sandbox)
            self.assertIn("<ClipboardRedirection>Disable</ClipboardRedirection>", sandbox)

            install_root = base / "installed-snapshot"
            installer = ROOT / "tools" / "Install-ReviewedSnapshot.ps1"
            installed = subprocess.run(
                [shell, "-NoProfile", "-File", str(installer),
                 "-Destination", str(install_root), "-SourceBundle", str(bundle),
                 "-PythonPath", sys.executable, "-SourceRoot", str(fake_repo)],
                capture_output=True, text=True, timeout=60, check=False,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr or installed.stdout)
            import json
            manifest = json.loads((install_root / "install-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], 1)
            self.assertEqual(Path(manifest["source_root"]), fake_repo.resolve())
            self.assertEqual(set(manifest["files"]), {
                path for path in expected if path.startswith("formfiller/")
            })

            launcher = install_root / "Run-FormFillerPrivate.ps1"
            # Exercise the generated PowerShell signature and Python argparse,
            # rather than a permissive stub that hides positional binding bugs.
            for paths in ([], ['-Workspace', str(base / 'private with spaces'),
                               '-Runtime', str(base / 'runtime with spaces')]):
                launched = subprocess.run(
                    [shell, '-NoProfile', '-File', str(launcher), *paths,
                     '-WebArgs', '--open'], capture_output=True, text=True, timeout=30)
                self.assertEqual(launched.returncode, 0, launched.stdout + launched.stderr)
                arguments = json.loads(launched.stdout)
                self.assertTrue(arguments['private'])
                self.assertTrue(arguments['open'])
                self.assertEqual(arguments['workspace'], str(base / 'private with spaces') if paths else None)
                self.assertEqual(arguments['runtime'], str(base / 'runtime with spaces') if paths else None)
            injected = install_root / "formfiller" / "injected.py"
            injected.write_text("# synthetic unlisted module\n", encoding="utf-8")
            checked = subprocess.run(
                [shell, "-NoProfile", "-File", str(launcher)],
                capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("inventory changed", checked.stderr + checked.stdout)
            injected.unlink()

            injected_binary = install_root / "formfiller" / "injected.pyd"
            injected_binary.write_bytes(b"synthetic only")
            checked = subprocess.run(
                [shell, "-NoProfile", "-File", str(launcher)],
                capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("inventory changed", checked.stderr + checked.stdout)
            injected_binary.unlink()

            modified = install_root / "formfiller" / source_allowlist()[0]
            modified.write_text("# tampered synthetic module\n", encoding="utf-8")
            checked = subprocess.run(
                [shell, "-NoProfile", "-File", str(launcher)],
                capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("hash check failed", checked.stderr + checked.stdout)


if __name__ == "__main__":
    unittest.main()
