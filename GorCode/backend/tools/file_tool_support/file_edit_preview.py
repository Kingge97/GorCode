"""
Edit preview and validation helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ..core_tool_support.base import ToolResult
from ..core_tool_support.tool_utils import build_permission_preview_result
from ...platform.encoding import read_text_with_fallback
from .file_diff import build_structured_diff, generate_git_diff, generate_unified_diff
from .file_edit_helpers import maybe_deserialize
from .file_edit_preconditions import PARTIAL_SNAPSHOT
from .file_settings import FileToolSettings


@dataclass(frozen=True)
class ContentRead:
    error: Optional[ToolResult]
    content: str


@dataclass(frozen=True)
class MatchValidation:
    error: Optional[ToolResult]
    match: Any


def prepare_edit_text(
    old_text: str,
    new_text: str,
    settings: FileToolSettings,
) -> tuple[str, str]:
    return (
        maybe_deserialize(old_text, settings.edit_deserialize),
        maybe_deserialize(new_text, settings.edit_deserialize),
    )


def read_edit_content(path: Path, encoding: str) -> ContentRead:
    content = read_text_with_fallback(path, encoding)
    if content is None:
        error = ToolResult(success=False, output="", error=f"Failed to read file with encoding: {encoding}")
        return ContentRead(error, "")
    return ContentRead(None, content)


def build_edit_preview(
    file_path: str,
    path: Path,
    old_content: str,
    new_content: str,
    match,
    replace_count: int,
    line_ending: str,
    encoding: str,
) -> ToolResult:
    return build_permission_preview_result(
        f"Ready to replace {replace_count} occurrence(s) in {file_path}",
        {
            "file_path": str(path),
            "occurrences_found": match.occurrences,
            "occurrences_to_replace": replace_count,
            "matched_text": match.match_text,
            "diff": generate_unified_diff(old_content, new_content, str(path)),
            "git_diff": generate_git_diff(old_content, new_content, str(path)),
            "structured_diff": build_structured_diff(old_content, new_content),
            "line_ending": line_ending,
            "new_content": new_content,
            "encoding": encoding,
        },
    )


def multiple_match_error(occurrences: int, snapshot_kind: str) -> str:
    if snapshot_kind == PARTIAL_SNAPSHOT:
        return (
            f"Multiple matches found ({occurrences}). "
            "Provide a longer old_text from the read region to make the edit unique."
        )
    return f"Multiple matches found ({occurrences}). Set replace_all=true or provide unique text."
