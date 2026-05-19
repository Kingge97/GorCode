"""
Edit precondition checks for full and partial file snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..core_tool_support.base import ToolResult
from .file_settings import FileToolSettings
from .file_state import FileState, FileStateCache


FULL_SNAPSHOT = "full"
PARTIAL_SNAPSHOT = "partial"
NO_SNAPSHOT = "none"


@dataclass(frozen=True)
class EditPrecondition:
    error: Optional[ToolResult]
    snapshot_kind: str


def validate_edit_preconditions(
    path: Path,
    cache: Optional[FileStateCache],
    settings: FileToolSettings,
    old_text: str,
    replace_all: bool,
) -> EditPrecondition:
    if not settings.enforce_read_before_write and not settings.enforce_mtime_check:
        return EditPrecondition(None, FULL_SNAPSHOT)
    if not cache:
        return _failed("No file snapshot available. Read the file or target region before editing.")

    state = cache.get_state(path)
    state_error = _validate_state(path, cache, state, settings)
    if state_error:
        return _failed(state_error)
    if not settings.enforce_read_before_write:
        return EditPrecondition(None, FULL_SNAPSHOT)
    if cache.has_full_snapshot(path):
        return EditPrecondition(None, FULL_SNAPSHOT)
    if replace_all and cache.has_partial_windows(path):
        return _failed(
            "replace_all is not allowed after a partial read. "
            "Read the full file first or use a unique old_text with replace_all=false."
        )
    if cache.has_partial_windows(path):
        return _validate_partial_window(path, cache, settings, old_text)
    return _failed("No file snapshot available. Read the file or target region before editing.")


def _validate_state(
    path: Path,
    cache: FileStateCache,
    state: Optional[FileState],
    settings: FileToolSettings,
) -> Optional[str]:
    if not settings.enforce_mtime_check:
        return None
    if not state:
        return "Missing file state for mtime check."
    if cache.is_modified_since(path, state):
        return "File modified since last read/edit/write; read the target region again before editing."
    return None


def _validate_partial_window(
    path: Path,
    cache: FileStateCache,
    settings: FileToolSettings,
    old_text: str,
) -> EditPrecondition:
    window = cache.find_partial_window_containing(path, old_text)
    if not window:
        return _failed(
            "Partial read snapshots exist, but old_text was not found in any read region. "
            "Read the region containing old_text before editing."
        )
    if settings.enforce_mtime_check and cache.is_modified_since(path, window):
        return _failed(
            "File modified since last read/edit/write; read the target region again before editing."
        )
    return EditPrecondition(None, PARTIAL_SNAPSHOT)


def _failed(message: str) -> EditPrecondition:
    return EditPrecondition(ToolResult(success=False, output="", error=message), NO_SNAPSHOT)
