"""Resolve private configuration and runtime locations for local FormFiller use."""
from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkspacePaths:
    config_dir: Path
    state_dir: Path
    profile_dir: Path
    external_runtime: bool = False
    external_workspace: bool = False
    installed_app: Path | None = None


class WorkspaceError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def resolve_workspace(project_root: str | Path | None = None) -> WorkspacePaths:
    """Use explicitly configured private directories, retaining legacy defaults."""
    root = Path(project_root or Path.cwd()).resolve()
    workspace_value = os.environ.get("FORM_FILLER_WORKSPACE")
    runtime_value = os.environ.get("FORM_FILLER_RUNTIME")
    installed_value = os.environ.get("FORM_FILLER_INSTALLED_APP")
    external_workspace = bool(workspace_value)
    external_runtime = bool(runtime_value)
    # Installer-owned locator keeps private paths out of the repository and task UI.
    # Read only the two directory fields needed by this process.
    local_app_data = os.environ.get("LOCALAPPDATA")
    locator = Path(local_app_data) / "FormFiller" / "paths.json" if local_app_data else None
    if locator and locator.exists():
        if locator.is_symlink() or not locator.is_file():
            raise WorkspaceError("workspace_locator_invalid")
        try:
            mapping = json.loads(locator.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise WorkspaceError("workspace_locator_invalid") from exc
        allowed = {"workspace", "runtime", "installed_app"}
        if not isinstance(mapping, dict) or set(mapping) != allowed:
            raise WorkspaceError("workspace_locator_invalid")
        if any(not isinstance(mapping.get(key), str) or not mapping[key].strip() for key in allowed):
            raise WorkspaceError("workspace_locator_invalid")
        if any(not Path(mapping[key]).expanduser().is_absolute() for key in allowed):
            raise WorkspaceError("workspace_locator_invalid")
        workspace_value = workspace_value or mapping["workspace"]
        runtime_value = runtime_value or mapping["runtime"]
        installed_value = installed_value or mapping["installed_app"]
        external_workspace = external_workspace or bool(mapping["workspace"])
        external_runtime = external_runtime or bool(mapping["runtime"])
    workspace = Path(workspace_value).expanduser().resolve() if workspace_value else root
    runtime = Path(runtime_value).expanduser().resolve() if runtime_value else root
    installed_app = Path(installed_value).expanduser().resolve() if isinstance(installed_value, str) and installed_value else None
    config_dir = workspace / "config"
    state_dir = runtime / "state"
    profile_dir = runtime / "browser-profile"
    return WorkspacePaths(config_dir, state_dir, profile_dir, external_runtime, external_workspace, installed_app)
