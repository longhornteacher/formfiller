"""Validate an installed FormFiller snapshot before it handles private data."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any


_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_IMPORT_SUFFIXES = {".py", ".pyc", ".pyd", ".dll"}
_FORBIDDEN_SUFFIXES = {".exe", ".bat", ".cmd", ".ps1"}


class DeploymentError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction()) if callable(is_junction) else False


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _has_link_component(path: Path) -> bool:
    try:
        absolute = path.absolute()
        current = Path(absolute.anchor)
        for part in absolute.parts[1:]:
            current = current / part
            if _is_link(current):
                return True
        return False
    except (OSError, RuntimeError):
        return True


def _inventory(root: Path) -> dict[str, Path]:
    package = root / "formfiller"
    if not package.is_dir() or _is_link(package):
        raise DeploymentError("install_inventory_invalid")
    result: dict[str, Path] = {}
    for current, dirnames, filenames in os.walk(package, followlinks=False):
        current_path = Path(current)
        kept_dirs = []
        for name in dirnames:
            child = current_path / name
            if _is_link(child):
                raise DeploymentError("install_link_detected")
            if name == "__pycache__":
                continue
            kept_dirs.append(name)
        dirnames[:] = kept_dirs
        for name in filenames:
            path = current_path / name
            if _is_link(path):
                raise DeploymentError("install_link_detected")
            relative = path.relative_to(root).as_posix()
            in_static = relative.startswith("formfiller/web_static/")
            if path.suffix.lower() in _FORBIDDEN_SUFFIXES:
                raise DeploymentError("install_forbidden_file")
            if path.suffix.lower() in _IMPORT_SUFFIXES or in_static:
                result[relative] = path
    return result


def validate_snapshot(root: str | Path, current_file: str | Path | None = None) -> dict[str, Any]:
    """Validate manifest inventory and hashes, returning safe summary metadata only."""
    if _has_link_component(Path(root)):
        raise DeploymentError("install_link_detected")
    try:
        install_root = Path(root).resolve(strict=True)
    except (OSError, RuntimeError, TypeError) as exc:
        raise DeploymentError("install_root_unavailable") from exc
    if not install_root.is_dir() or _is_link(Path(root)):
        raise DeploymentError("install_root_invalid")
    manifest_path = install_root / "install-manifest.json"
    if _is_link(manifest_path):
        raise DeploymentError("install_manifest_invalid")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DeploymentError("install_manifest_invalid") from exc
    if (not isinstance(manifest, dict) or set(manifest) != {"version", "source_root", "files"}
            or type(manifest.get("version")) is not int or manifest.get("version") != 1):
        raise DeploymentError("install_manifest_invalid")
    source_text = manifest.get("source_root")
    if not isinstance(source_text, str) or not source_text:
        raise DeploymentError("install_manifest_invalid")
    try:
        source_root = Path(source_text).resolve(strict=False)
    except (OSError, RuntimeError, TypeError) as exc:
        raise DeploymentError("install_source_invalid") from exc
    if (_inside(install_root, source_root) or _inside(source_root, install_root)):
        raise DeploymentError("install_source_overlap")
    listed = manifest.get("files")
    if not isinstance(listed, dict):
        raise DeploymentError("install_manifest_invalid")
    expected: dict[str, str] = {}
    for name, digest in listed.items():
        if not isinstance(name, str) or not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            raise DeploymentError("install_manifest_invalid")
        relative = PurePosixPath(name)
        if (relative.is_absolute() or ".." in relative.parts or "\\" in name
                or not name.startswith("formfiller/") or name in expected):
            raise DeploymentError("install_manifest_invalid")
        if ("__pycache__" in relative.parts
                or not (Path(name).suffix.lower() in _IMPORT_SUFFIXES or name.startswith("formfiller/web_static/"))):
            raise DeploymentError("install_manifest_invalid")
        expected[name] = digest
    actual = _inventory(install_root)
    if set(actual) != set(expected):
        raise DeploymentError("install_inventory_mismatch")
    for name, path in actual.items():
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise DeploymentError("install_file_unreadable") from exc
        if digest != expected[name]:
            raise DeploymentError("install_hash_mismatch")
    if current_file is not None:
        try:
            current = Path(current_file).resolve(strict=True)
            relative = current.relative_to(install_root).as_posix()
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            raise DeploymentError("install_current_file_invalid") from exc
        if _is_link(Path(current_file)) or relative not in expected:
            raise DeploymentError("install_current_file_invalid")
    return {"version": 1, "files": len(expected)}
