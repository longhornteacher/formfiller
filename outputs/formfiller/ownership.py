"""Fail-closed pairing of private workspace config and local runtime state."""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any


_MARKER = ".formfiller-owner.json"
_OWNER = re.compile(r"^[a-f0-9]{32}$")


class RuntimeOwnerError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _read(path: Path) -> str:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeOwnerError("runtime_owner_missing") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeOwnerError("runtime_owner_invalid") from exc
    owner = value.get("owner_id") if isinstance(value, dict) else None
    if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
        raise RuntimeOwnerError("runtime_owner_invalid")
    return owner


def _create(path: Path, owner_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps({"owner_id": owner_id}, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeOwnerError("runtime_owner_exists") from exc
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        # O_EXCL proves this invocation created the path, so it may clean up
        # its partial write without touching a prior binding.
        try:
            path.unlink()
        except OSError:
            pass
        raise RuntimeOwnerError("runtime_owner_write_failed") from exc


def bind_runtime(workspace_root: str | Path, runtime_root: str | Path) -> str:
    """Create the one-time owner pair during an explicit local migration/setup."""
    workspace = Path(workspace_root).resolve()
    runtime = Path(runtime_root).resolve()
    workspace_marker = workspace / _MARKER
    runtime_marker = runtime / _MARKER
    if workspace_marker.exists() or runtime_marker.exists():
        raise RuntimeOwnerError("runtime_owner_exists")
    owner_id = uuid.uuid4().hex
    created: list[Path] = []
    try:
        _create(workspace_marker, owner_id)
        created.append(workspace_marker)
        if runtime_marker != workspace_marker:
            _create(runtime_marker, owner_id)
            created.append(runtime_marker)
    except Exception:
        for marker in reversed(created):
            _remove_if_owner(marker, owner_id)
        raise
    return owner_id


def _remove_if_owner(marker: Path, owner_id: str) -> None:
    try:
        if _read(marker) == owner_id:
            marker.unlink()
    except RuntimeOwnerError:
        return


def unbind_runtime(workspace_root: str | Path, runtime_root: str | Path, owner_id: str) -> None:
    """Roll back a just-created pair only when both markers still match its token."""
    if not isinstance(owner_id, str) or not _OWNER.fullmatch(owner_id):
        raise RuntimeOwnerError("runtime_owner_invalid")
    workspace = Path(workspace_root).resolve()
    runtime = Path(runtime_root).resolve()
    workspace_marker = workspace / _MARKER
    runtime_marker = runtime / _MARKER
    if _read(workspace_marker) != owner_id or _read(runtime_marker) != owner_id:
        raise RuntimeOwnerError("runtime_owner_mismatch")
    _remove_if_owner(runtime_marker, owner_id)
    if workspace_marker != runtime_marker:
        _remove_if_owner(workspace_marker, owner_id)


def verify_runtime_owner(workspace_root: str | Path, runtime_root: str | Path) -> None:
    """Require matching setup markers; never infer or repair ownership."""
    workspace = Path(workspace_root).resolve()
    runtime = Path(runtime_root).resolve()
    owner = _read(workspace / _MARKER)
    if owner != _read(runtime / _MARKER):
        raise RuntimeOwnerError("runtime_owner_mismatch")
