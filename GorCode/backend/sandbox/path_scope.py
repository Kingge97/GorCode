"""
Workspace path scope checks.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def resolve_workspace(workspace_root: Path) -> Path:
    """Resolve the workspace root for stable comparisons."""
    return Path(workspace_root).expanduser().resolve()


def resolve_target_path(path_value: str, workspace_root: Path, cwd: Optional[Path]) -> Path:
    """Resolve a target path relative to cwd or workspace root."""
    raw = Path(str(path_value)).expanduser()
    base = Path(cwd).expanduser() if cwd else workspace_root
    target = raw if raw.is_absolute() else base / raw
    return target.resolve()


def is_in_workspace(target_path: Path, workspace_root: Path) -> bool:
    """Return true when target_path resolves inside workspace_root."""
    target = _normalize_for_platform(target_path.resolve())
    root = _normalize_for_platform(resolve_workspace(workspace_root))
    try:
        return os.path.commonpath([root, target]) == root
    except ValueError:
        return False


def path_scope(path_value: str, workspace_root: Path, cwd: Optional[Path]) -> str:
    """Classify a path as workspace or outside_workspace."""
    target = resolve_target_path(path_value, workspace_root, cwd)
    if is_in_workspace(target, workspace_root):
        return "workspace"
    return "outside_workspace"


def _normalize_for_platform(path: Path) -> str:
    text = os.path.normpath(str(path))
    if os.name == "nt":
        return os.path.normcase(text)
    return text
