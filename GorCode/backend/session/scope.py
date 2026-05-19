"""
Project scope helpers for session history.
"""

import os
from pathlib import Path


SCOPE_PROJECT = "project"
SCOPE_ALL = "all"


def normalize_project_path(path: str) -> str:
    """Return a deterministic absolute project path, or empty for no owner."""
    text = str(path or "").strip()
    if not text:
        return ""
    resolved = Path(text).expanduser().resolve(strict=False)
    return os.path.normpath(str(resolved))


def paths_match(left: str, right: str) -> bool:
    """Compare two non-empty normalized project paths."""
    left_norm = normalize_project_path(left)
    right_norm = normalize_project_path(right)
    if not left_norm or not right_norm:
        return False
    if os.name == "nt":
        return left_norm.lower() == right_norm.lower()
    return left_norm == right_norm


def normalize_scope(scope: str) -> str:
    """Normalize history scope to project or all."""
    value = str(scope or SCOPE_PROJECT).strip().lower()
    if value == SCOPE_ALL:
        return SCOPE_ALL
    return SCOPE_PROJECT

