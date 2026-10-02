"""Crash-safe local state for the FormFiller runner.

Only aliases, dates, state codes, and opaque fingerprints are written here.
No URLs, names, answers, or browser exception text are persisted.
"""

from __future__ import annotations

import json
import os
import re
import socket
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class StateError(RuntimeError):
    """A state operation failed safely; ``code`` is suitable for display."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


_ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_STATUSES = {"pending", "submitting", "submitted", "failed", "uncertain"}
_TRANSITIONS = {
    "pending": {"submitting", "failed"},
    "failed": {"submitting", "failed"},
    "submitting": {"submitted", "uncertain"},
    "submitted": set(),
    "uncertain": set(),
}


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
        # Persist the directory entry where the platform supports directory fsync.
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


class StateStore:
    """Per-date alias state, global schema approvals, and a fail-closed lock."""

    def __init__(self, root: str | Path, today: date | str):
        self.root = Path(root)
        self.day = today.isoformat() if isinstance(today, date) else str(today)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.day):
            raise StateError("invalid_date")
        try:
            date.fromisoformat(self.day)
        except ValueError as exc:
            raise StateError("invalid_date") from exc
        self.day_dir = self.root / self.day
        self.day_file = self.day_dir / "state.json"
        self.lock_file = self.root / ".runner.lock"
        self.approval_file = self.root / "schema_approvals.json"

    @staticmethod
    def _alias(alias: str) -> str:
        if not isinstance(alias, str) or not _ALIAS_RE.fullmatch(alias):
            raise StateError("invalid_alias")
        return alias

    def _read_json(self, path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StateError("state_unreadable") from exc

    def _day_data(self) -> dict[str, Any]:
        data = self._read_json(self.day_file, {"date": self.day, "forms": {}})
        if not isinstance(data, dict) or data.get("date") != self.day or not isinstance(data.get("forms"), dict):
            raise StateError("state_invalid")
        return data

    @staticmethod
    def _summary(data: dict[str, Any]) -> dict[str, int]:
        return {status: sum(isinstance(row, dict) and row.get("status") == status for row in data["forms"].values())
                for status in sorted(_STATUSES)}

    def read(self, alias: str) -> dict[str, Any] | None:
        alias = self._alias(alias)
        record = self._day_data()["forms"].get(alias)
        if record is None:
            return None
        if not isinstance(record, dict) or record.get("status") not in _STATUSES:
            raise StateError("state_invalid")
        return dict(record)

    def bind_config(self, alias: str, fingerprint: str) -> dict[str, Any]:
        """Bind this alias to today's config, refusing same-day edits after first use."""
        alias = self._alias(alias)
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            raise StateError("invalid_fingerprint")
        data = self._day_data()
        record = data["forms"].get(alias)
        if record is None:
            record = {"status": "pending", "config": fingerprint}
            data["forms"][alias] = record
            data["summary"] = self._summary(data)
            _atomic_json(self.day_file, data)
        elif not isinstance(record, dict) or record.get("status") not in _STATUSES:
            raise StateError("state_invalid")
        elif record.get("config") != fingerprint:
            # Submitted/uncertain records must remain immutable and never become retryable.
            if record.get("status") in {"submitted", "submitting", "uncertain"}:
                return dict(record)
            raise StateError("config_changed")
        return dict(record)

    def transition(self, alias: str, expected: str | set[str] | tuple[str, ...], status: str, code: str | None = None) -> dict[str, Any]:
        alias = self._alias(alias)
        if status not in _STATUSES:
            raise StateError("invalid_status")
        expected_set = {expected} if isinstance(expected, str) else set(expected)
        data = self._day_data()
        record = data["forms"].get(alias)
        if not isinstance(record, dict) or record.get("status") not in _STATUSES:
            raise StateError("state_missing")
        old = record["status"]
        if old not in expected_set:
            raise StateError("state_conflict")
        if status != old and status not in _TRANSITIONS[old]:
            raise StateError("terminal_submission_state")
        record["status"] = status
        if code is None:
            record.pop("code", None)
        else:
            if not re.fullmatch(r"[a-z0-9_]{1,48}", code):
                raise StateError("invalid_code")
            record["code"] = code
        data["forms"][alias] = record
        data["summary"] = self._summary(data)
        _atomic_json(self.day_file, data)
        return dict(record)

    def log(self, alias: str | None, status: str, code: str | None = None) -> None:
        """Append one sanitized event; caller holds the runner lock."""
        if alias is not None:
            alias = self._alias(alias)
        if status not in _STATUSES and status not in {
            "preview", "skipped", "calendar_blocked", "calendar_error", "schema_captured",
            "schema_approved", "preflight_failed", "summary",
        }:
            raise StateError("invalid_status")
        event: dict[str, str] = {"date": self.day, "status": status}
        if alias is not None:
            event["alias"] = alias
        if code is not None:
            if not re.fullmatch(r"[a-z0-9_]{1,48}", code):
                raise StateError("invalid_code")
            event["code"] = code
        self.day_dir.mkdir(parents=True, exist_ok=True)
        path = self.day_dir / "events.jsonl"
        try:
            with path.open("ab") as stream:
                stream.write(_json_bytes(event))
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise StateError("log_write_failed") from exc

    def summary(self, aliases: list[str] | tuple[str, ...]) -> dict[str, int]:
        data = self._day_data()
        counts = {status: 0 for status in sorted(_STATUSES)}
        counts["missing"] = 0
        for alias in aliases:
            self._alias(alias)
            record = data["forms"].get(alias)
            if record is None:
                counts["missing"] += 1
            elif isinstance(record, dict) and record.get("status") in _STATUSES:
                counts[record["status"]] += 1
            else:
                raise StateError("state_invalid")
        return counts

    def log_summary(self, counts: dict[str, int]) -> None:
        expected = {"pending", "submitting", "submitted", "failed", "uncertain", "missing"}
        if set(counts) != expected or any(type(value) is not int or value < 0 for value in counts.values()):
            raise StateError("invalid_summary")
        self.day_dir.mkdir(parents=True, exist_ok=True)
        path = self.day_dir / "events.jsonl"
        event = {"date": self.day, "status": "summary", "counts": counts}
        try:
            with path.open("ab") as stream:
                stream.write(_json_bytes(event))
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise StateError("log_write_failed") from exc

    def approvals(self) -> dict[str, str]:
        data = self._read_json(self.approval_file, {"forms": {}})
        if not isinstance(data, dict) or not isinstance(data.get("forms"), dict):
            raise StateError("approval_state_invalid")
        return {str(k): v for k, v in data["forms"].items() if isinstance(v, str)}

    def record_schema(self, alias: str, fingerprint: str, approved: bool = False, config_fingerprint: str | None = None) -> None:
        alias = self._alias(alias)
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            raise StateError("invalid_fingerprint")
        data = self._read_json(self.approval_file, {"forms": {}})
        if not isinstance(data, dict) or not isinstance(data.get("forms"), dict):
            raise StateError("approval_state_invalid")
        prior = data["forms"].get(alias)
        if approved and not isinstance(prior, dict):
            raise StateError("schema_not_captured")
        if approved and prior.get("captured") != fingerprint:
            raise StateError("schema_fingerprint_mismatch")
        if config_fingerprint is not None and not re.fullmatch(r"[a-f0-9]{64}", config_fingerprint):
            raise StateError("invalid_fingerprint")
        data["forms"][alias] = {
            "captured": fingerprint,
            "approved_schema": fingerprint if approved else None,
            "approved_config": config_fingerprint if approved else None,
        }
        _atomic_json(self.approval_file, data)

    def schema_approved(self, alias: str, fingerprint: str, config_fingerprint: str | None = None) -> bool:
        alias = self._alias(alias)
        data = self._read_json(self.approval_file, {"forms": {}})
        try:
            record = data["forms"][alias]
            return (
                record.get("captured") == fingerprint
                and record.get("approved_schema") == fingerprint
                and (config_fingerprint is None or record.get("approved_config") == config_fingerprint)
            )
        except (KeyError, TypeError, AttributeError):
            return False

    @contextmanager
    def lock(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        lock_data = {"pid": os.getpid(), "host": socket.gethostname(), "created_utc": datetime.now(timezone.utc).isoformat()}
        try:
            fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            # A lock is never stolen automatically. This is safe for live and stale locks.
            raise StateError("lock_exists") from exc
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(_json_bytes(lock_data))
                stream.flush()
                os.fsync(stream.fileno())
            yield
        finally:
            try:
                self.lock_file.unlink()
            except FileNotFoundError:
                pass
