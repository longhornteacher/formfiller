"""Private form configuration CRUD with immutable, safe internal IDs.

Never return URLs, schemas, or answers from listing methods. Full records are
available only through get_form for local, authenticated application logic.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ALLOWED = {"name", "url", "schema", "answers"}
_FORM_HOSTS = {"forms.office.com", "forms.cloud.microsoft"}


def _validate_schema(value: Any) -> None:
    if value is not None and (not isinstance(value, dict) or not isinstance(value.get("questions"), list)):
        raise FormStoreError("invalid_schema")


def _validate_answers(value: Any) -> None:
    if value is not None and (not isinstance(value, list) or any(not isinstance(row, dict) for row in value)):
        raise FormStoreError("invalid_answers")


def _form_key(url: Any) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise FormStoreError("invalid_url") from exc
    if (parsed.scheme != "https" or hostname not in _FORM_HOSTS or parsed.username or parsed.password
            or port not in (None, 443)):
        raise FormStoreError("invalid_url")
    identifiers = parse_qs(parsed.query).get("id", [])
    if len(identifiers) != 1 or not identifiers[0]:
        raise FormStoreError("invalid_url")
    return identifiers[0]


class FormStoreError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class FormStore:
    """Atomically manage the private forms.json file under one config directory."""

    def __init__(self, config_dir: str | Path):
        self.config_dir = Path(config_dir)
        self.path = self.config_dir / "forms.json"

    def _read(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"forms": []}, []
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FormStoreError("forms_config") from exc
        forms = value.get("forms") if isinstance(value, dict) else None
        if not isinstance(forms, list):
            raise FormStoreError("forms_config")
        seen: set[str] = set()
        for row in forms:
            if not isinstance(row, dict):
                raise FormStoreError("forms_config")
            # Legacy records are read as-is; alias is the persisted identity.
            form_id = row.get("id", row.get("alias"))
            if not isinstance(form_id, str) or not _ID_RE.fullmatch(form_id) or form_id in seen:
                raise FormStoreError("forms_config")
            if "alias" in row and row["alias"] != form_id:
                raise FormStoreError("forms_config")
            seen.add(form_id)
        return value, forms

    def _write(self, document: dict[str, Any]) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".forms-", suffix=".tmp", dir=self.config_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(document, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    @staticmethod
    def _identity(row: dict[str, Any]) -> str:
        return row.get("id", row.get("alias"))

    @staticmethod
    def _name(row: dict[str, Any], ordinal: int) -> str:
        value = row.get("name")
        return value if isinstance(value, str) and value.strip() else f"Form {ordinal}"

    def list_forms(self) -> list[dict[str, str]]:
        _, forms = self._read()
        return [
            {"id": self._identity(row), "name": self._name(row, i)}
            for i, row in enumerate(forms, 1) if row.get("active", True) is True
        ]

    def get_form(self, form_id: str) -> dict[str, Any]:
        if not isinstance(form_id, str) or not _ID_RE.fullmatch(form_id):
            raise FormStoreError("unknown_form")
        _, forms = self._read()
        for i, row in enumerate(forms, 1):
            if self._identity(row) == form_id and row.get("active", True) is True:
                form = dict(row)
                form["id"] = form_id
                form["alias"] = form_id
                form["name"] = self._name(form, i)
                return form
        raise FormStoreError("unknown_form")

    def create_form(self, name: str, fields: dict[str, Any] | None = None) -> dict[str, str]:
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
            raise FormStoreError("invalid_name")
        fields = {} if fields is None else fields
        if not isinstance(fields, dict) or set(fields) - {"url", "schema", "answers"}:
            raise FormStoreError("invalid_form_update")
        _validate_schema(fields.get("schema"))
        _validate_answers(fields.get("answers", []))
        document, forms = self._read()
        candidate_url = fields.get("url", "")
        candidate_key = _form_key(candidate_url)
        if candidate_key is not None:
            for row in forms:
                try:
                    prior_key = _form_key(row.get("url", ""))
                except FormStoreError:
                    continue
                if prior_key == candidate_key:
                    raise FormStoreError("duplicate_form_url")
        while True:
            form_id = "form_" + uuid.uuid4().hex
            if all(self._identity(row) != form_id for row in forms):
                break
        forms.append({"id": form_id, "alias": form_id, "name": name.strip(),
                      "url": candidate_url or "", "schema": fields.get("schema"),
                      "answers": fields.get("answers", []), "active": True})
        document["forms"] = forms
        self._write(document)
        return {"id": form_id, "name": name.strip()}

    def update_form(self, form_id: str, changes: dict[str, Any]) -> dict[str, str]:
        if not isinstance(changes, dict) or set(changes) - _ALLOWED:
            raise FormStoreError("invalid_form_update")
        document, forms = self._read()
        for i, row in enumerate(forms, 1):
            if self._identity(row) != form_id or row.get("active", True) is not True:
                continue
            updated = dict(row)
            for key, value in changes.items():
                if key == "name":
                    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 120:
                        raise FormStoreError("invalid_name")
                    updated[key] = value.strip()
                elif key == "url":
                    if value is not None and (not isinstance(value, str) or (value and not value.startswith("https://"))):
                        raise FormStoreError("invalid_url")
                    candidate = value or ""
                    candidate_key = _form_key(candidate)
                    if candidate_key is not None:
                        for other in forms:
                            if other is row or self._identity(other) == form_id:
                                continue
                            try:
                                if _form_key(other.get("url", "")) == candidate_key:
                                    raise FormStoreError("duplicate_form_url")
                            except FormStoreError as exc:
                                if exc.code == "duplicate_form_url":
                                    raise
                    updated[key] = candidate
                else:
                    if key == "schema":
                        _validate_schema(value)
                    else:
                        _validate_answers(value)
                    updated[key] = value
            # ID and legacy alias cannot be edited through this interface.
            forms[i - 1] = updated
            document["forms"] = forms
            self._write(document)
            return {"id": form_id, "name": self._name(updated, i)}
        raise FormStoreError("unknown_form")

    def archive_form(self, form_id: str) -> dict[str, str]:
        document, forms = self._read()
        for i, row in enumerate(forms, 1):
            if self._identity(row) != form_id or row.get("active", True) is not True:
                continue
            row = dict(row)
            row["active"] = False
            forms[i - 1] = row
            document["forms"] = forms
            self._write(document)
            return {"id": form_id, "name": self._name(row, i)}
        raise FormStoreError("unknown_form")
