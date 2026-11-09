"""Relocate private files without displaying their contents or resetting state."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

from .ownership import bind_runtime
from .state import _atomic_json


class MigrationError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def fingerprints(path):
    """Used internally for byte verification; never printed or exported."""
    def digest(file):
        with file.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    if path.is_file():
        return {".": digest(path)}
    result = {}
    for file in path.rglob("*"):
        if file.is_symlink() or file.is_junction():
            raise MigrationError("source_link_not_allowed")
        if file.is_file():
            result[file.relative_to(path).as_posix()] = digest(file)
    return result


def _exclusive(path, payload, code):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise MigrationError(code) from None
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def migrate(source_root, workspace_root, runtime_root, *, installed_app=None):
    source, runtime = Path(source_root).resolve(), Path(runtime_root).resolve()
    outputs = source / "outputs"
    if not (outputs / "config" / "forms.json").is_file():
        raise MigrationError("legacy_configuration_missing")
    for raw in (source_root, workspace_root, runtime_root):
        path = Path(raw).absolute()
        if any(part.is_symlink() or part.is_junction() for part in (path, *path.parents)):
            raise MigrationError("migration_link_not_allowed")
    payload = json.dumps({"migration_token": uuid.uuid4().hex}).encode("ascii")
    gate, lock = outputs / ".migration.lock", outputs / "state" / ".runner.lock"
    _exclusive(gate, payload, "migration_in_progress")
    locked = False
    try:
        _exclusive(lock, payload, "run_locked")
        locked = True
        return _migrate(source_root, workspace_root, runtime_root, installed_app=installed_app)
    finally:
        # Remove only this invocation's lock, including after its directory moves.
        for owned in ([lock, runtime / "state" / ".runner.lock"] if locked else []) + [gate]:
            if owned.is_file() and owned.read_bytes() == payload:
                owned.unlink()


def _migrate(source_root, workspace_root, runtime_root, *, installed_app=None):
    for value in (source_root, workspace_root, runtime_root):
        path = Path(value).absolute()
        if any(part.is_symlink() or part.is_junction() for part in (path, *path.parents)):
            raise MigrationError("migration_link_not_allowed")
    source, workspace, runtime = map(lambda value: Path(value).resolve(), (source_root, workspace_root, runtime_root))
    if (workspace.is_relative_to(source) or runtime.is_relative_to(source)
            or source.is_relative_to(workspace) or source.is_relative_to(runtime) or workspace == runtime):
        raise MigrationError("external_paths_required")
    if runtime.is_relative_to(workspace) or workspace.is_relative_to(runtime):
        raise MigrationError("runtime_must_not_sync")
    outputs = source / "outputs"
    if not (outputs / "config" / "forms.json").is_file():
        raise MigrationError("legacy_configuration_missing")
    locator = Path(os.environ["LOCALAPPDATA"]) / "FormFiller" / "paths.json"
    if locator.exists():
        raise MigrationError("workspace_locator_exists")
    if any((root / ".formfiller-owner.json").exists() for root in (workspace, runtime)):
        raise MigrationError("runtime_owner_exists")
    if installed_app:
        from .deployment import validate_snapshot
        validate_snapshot(installed_app)
    # A legacy checkout keeps one district workbook named "<district>_<year>_Instructional_Dates_Full_Text.xlsx".
    workbooks = sorted(source.glob("*_Instructional_Dates_Full_Text.xlsx"))
    legacy_workbook = workbooks[0] if len(workbooks) == 1 else source / "Instructional_Dates_Full_Text.xlsx"
    operations = [
        (outputs / "config" / "browser-profile", runtime / "browser-profile"),
        (outputs / "state", runtime / "state"),
        (outputs / "config", workspace / "config"),
        (outputs / "reports", workspace / "reports"),
        (source / "Accommodation Log.txt", workspace / "sources" / "Accommodation Log.txt"),
        (legacy_workbook, workspace / "sources" / legacy_workbook.name),
    ]
    operations = [(old, new) for old, new in operations if old.exists()]
    for old, new in operations:
        if not old.is_relative_to(source) or not (new.is_relative_to(workspace) or new.is_relative_to(runtime)):
            raise MigrationError("path_outside_workspace")
        if (any(part.is_symlink() or part.is_junction() for part in (old, *old.parents, new, *new.parents))
                or new.exists()):
            raise MigrationError("migration_destination_conflict")
    calendar_path = outputs / "config" / "calendar.json"
    calendar_bytes = calendar_path.read_bytes() if calendar_path.exists() else None
    calendar = json.loads(calendar_bytes) if calendar_bytes else None
    settings_path = outputs / "config" / "settings.json"
    settings_bytes = settings_path.read_bytes() if settings_path.exists() else None
    settings = json.loads(settings_bytes) if settings_bytes else None
    configured_calendar = Path(settings.get("calendar_path", "calendar.json")) if isinstance(settings, dict) else None
    relocate_setting = bool(configured_calendar and configured_calendar.is_absolute()
                            and configured_calendar.resolve() == calendar_path.resolve())
    workbook_old = legacy_workbook
    workbook_new = workspace / "sources" / workbook_old.name
    relocate_calendar = bool(calendar and calendar.get("source_kind") == "district_workbook"
                             and Path(calendar.get("workbook_path", "")).resolve() == workbook_old)
    if calendar and calendar.get("source_kind") == "district_workbook" and not relocate_calendar:
        raise MigrationError("calendar_source_location_unexpected")
    if relocate_calendar and not workbook_old.is_file():
        raise MigrationError("calendar_source_missing")
    completed = []
    file_count = 0
    owner = None
    try:
        for old, new in operations:
            before = fingerprints(old)
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(new))
            completed.append((old, new))
            if fingerprints(new) != before:
                raise MigrationError("migration_integrity_failed")
            file_count += len(before)
        if relocate_calendar:
            # This relocates provenance only. Approval, export timestamp, digest,
            # coverage, and every instructional date stay byte-for-byte equivalent.
            calendar["workbook_path"] = str(workbook_new)
            _atomic_json(workspace / "config" / "calendar.json", calendar)
        if relocate_setting:
            settings["calendar_path"] = "calendar.json"
            _atomic_json(workspace / "config" / "settings.json", settings)
        owner = bind_runtime(workspace, runtime)
        mapping = {"workspace": str(workspace), "runtime": str(runtime)}
        if installed_app:
            mapping["installed_app"] = str(Path(installed_app).resolve())
        _atomic_json(locator, mapping)
    except Exception:
        rollback_ok = True
        if owner is not None:
            for root in (workspace, runtime):
                marker = root / ".formfiller-owner.json"
                try:
                    if json.loads(marker.read_bytes()).get("owner_id") != owner:
                        raise MigrationError("runtime_owner_changed")
                    marker.unlink()
                except Exception:
                    rollback_ok = False
        if calendar_bytes is not None and (workspace / "config" / "calendar.json").exists():
            try:
                (workspace / "config" / "calendar.json").write_bytes(calendar_bytes)
            except Exception:
                rollback_ok = False
        if settings_bytes is not None and (workspace / "config" / "settings.json").exists():
            try:
                (workspace / "config" / "settings.json").write_bytes(settings_bytes)
            except Exception:
                rollback_ok = False
        for old, new in reversed(completed):
            try:
                old.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(new), str(old))
            except Exception:
                rollback_ok = False
        raise MigrationError("migration_failed_rolled_back" if rollback_ok else "migration_recovery_required") from None
    return {"groups": len(completed), "files": file_count}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--installed-app", type=Path)
    args = parser.parse_args(argv)
    try:
        result = migrate(args.source_root, args.workspace, args.runtime, installed_app=args.installed_app)
        print(f"migration=complete groups={result['groups']} files={result['files']}")
        return 0
    except Exception as exc:
        code = getattr(exc, "code", "migration_failed")
        print("migration=blocked code=" + code)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
