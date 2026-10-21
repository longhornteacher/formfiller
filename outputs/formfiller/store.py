"""Private form configuration CRUD with immutable, safe internal IDs.

Never return URLs, schemas, or answers from listing methods. Full records are
available only through get_form for local, authenticated application logic.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import tempfile
import uuid
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .state import _atomic_replace


_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ALLOWED = {"name", "url", "schema", "answers", "scheduled"}
_FORM_HOSTS = {"forms.office.com", "forms.cloud.microsoft"}


def template_fingerprint(form):
    value = {key: form.get(key) for key in ("url", "schema", "answers")}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


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
            _atomic_replace(temp_name, self.path)
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
                      "answers": fields.get("answers", []), "active": True, "scheduled": False})
        document["forms"] = forms
        self._write(document)
        return {"id": form_id, "name": name.strip()}

    @staticmethod
    def submission_seed(form, *, exact_schema=True):
        """Use confirmed answers unless the user has saved newer template edits.

        Exact mode never displays a different answer policy from the approved
        template. Schema refresh can map the last observed questions explicitly.
        """
        prior = form.get("last_submission")
        if not isinstance(prior, dict):
            return form, "saved_answers"
        if prior.get("url") != form.get("url") or prior.get("template_fingerprint") != template_fingerprint(form):
            return form, "saved_changes"
        questions = (prior.get("schema") or {}).get("questions")
        answers = prior.get("answers")
        if (not isinstance(questions, list) or not isinstance(answers, list)
                or len(questions) != len(answers) or any(not isinstance(a, dict) for a in answers)):
            return form, "saved_answers"
        if exact_schema:
            def policy(rows):
                return [{"kind": "date"} if row.get("kind") == "date" else row for row in rows]
            if prior["schema"] != form.get("schema") or policy(answers) != policy(form.get("answers") or []):
                return form, "saved_answers"
        return prior, "last_submission"

    def record_submission(self, form_id, submitted_form, submitted_on, fingerprint):
        """Persist confirmed contents only, under the caller's shared runner lock.

        This metadata cannot be set through form CRUD, never changes the approved
        template, and never belongs in sanitized runtime state or logs.
        """
        day = date.fromisoformat(str(submitted_on))
        _validate_schema(submitted_form.get("schema"))
        _validate_answers(submitted_form.get("answers"))
        document, forms = self._read()
        for row in forms:
            if self._identity(row) != form_id or row.get("active", True) is not True:
                continue
            if (submitted_form.get("alias") != form_id or row.get("url") != submitted_form.get("url")
                    or template_fingerprint(row) != fingerprint):
                raise FormStoreError("submission_template_changed")
            prior = row.get("last_submission")
            if isinstance(prior, dict) and prior.get("date", "") > day.isoformat():
                raise FormStoreError("submission_date_older")
            answers = deepcopy(submitted_form["answers"])
            for answer in answers:
                if answer.get("kind") == "date":
                    answer["value"] = f"{day.month}/{day.day}/{day.year}"
            row["last_submission"] = {"date": day.isoformat(), "url": submitted_form["url"],
                "schema": deepcopy(submitted_form["schema"]), "answers": answers,
                "template_fingerprint": fingerprint}
            self._write(document)
            return
        raise FormStoreError("unknown_form")

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
                elif key == "scheduled":
                    if type(value) is not bool:
                        raise FormStoreError("invalid_schedule")
                    updated[key] = value
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
