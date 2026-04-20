"""
Edit Tool
=========

Edit file contents with permission preview.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .core_tool_support.base import BaseTool, ToolResult
from .file_tool_support.file_diff import build_structured_diff, generate_git_diff, generate_unified_diff
from .file_tool_support.file_edit_helpers import (
    apply_line_endings,
    find_match_text,
    maybe_deserialize,
    normalize_trailing_whitespace,
)
from .file_tool_support.file_io import write_text_file
from .file_tool_support.file_read_helpers import check_file_size
from .file_tool_support.file_settings import FileToolSettings
from .file_tool_support.file_state import FileStateCache
from .file_tool_support.file_utils import detect_line_ending
from .core_tool_support.path_validation import resolve_and_validate_path
from .core_tool_support.tool_utils import (
    build_parameters_schema,
    build_permission_preview_result,
    resolve_encoding,
    tool_error_result,
)
from ..lsp import LspManager
from ..platform.detector import get_platform_info
from ..platform.encoding import read_text_with_fallback


class EditTool(BaseTool):
    """Tool for editing files by replacing text."""

    name = "edit"
    description = "Edit a file by replacing exact text matches. Use this for precise modifications."
    category = "file"
    needs_encoding = True
    requires_permission = True

    def __init__(
        self,
        default_encoding: str = "utf-8",
        file_state_cache: Optional[FileStateCache] = None,
        settings: Optional[FileToolSettings] = None,
        lsp_manager: Optional[LspManager] = None,
    ) -> None:
        super().__init__(default_encoding=default_encoding)
        self._file_state_cache = file_state_cache
        self._settings = settings or FileToolSettings()
        self._lsp_manager = lsp_manager

    def execute(
        self,
        file_path: str,
        old_text: str,
        new_text: str,
        replace_all: bool = False,
        encoding: str = None,
    ) -> ToolResult:
        """
        Edit file by replacing text.

        Args:
            file_path: Path to the file to edit
            old_text: Text to find and replace
            new_text: Text to replace with
            replace_all: Replace all occurrences if True
            encoding: File encoding

        Returns:
            ToolResult with edit status and permission metadata
        """
        try:
            path, validation_error = resolve_and_validate_path(file_path, "file")
            if validation_error:
                return validation_error

            size_error = check_file_size(path, self._settings, check_read_limit=False)
            if size_error:
                return size_error

            precheck_error = _validate_preconditions(path, self._file_state_cache, self._settings)
            if precheck_error:
                return precheck_error

            enc = resolve_encoding(encoding, self.default_encoding)
            content = read_text_with_fallback(path, enc)
            if content is None:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Failed to read file with encoding: {enc}",
                )

            prepared_old = maybe_deserialize(old_text, self._settings.edit_deserialize)
            prepared_new = maybe_deserialize(new_text, self._settings.edit_deserialize)

            match = find_match_text(content, prepared_old, self._settings)
            if not match:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Text not found in file: {prepared_old[:100]}...",
                )

            if match.occurrences > 1 and not replace_all:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Multiple matches found ({match.occurrences}). "
                        "Set replace_all=true or provide unique text."
                    ),
                    metadata={
                        "occurrences_found": match.occurrences,
                    },
                )

            replace_count = match.occurrences if replace_all else 1
            new_content = content.replace(match.match_text, prepared_new, replace_count)
            line_ending = _resolve_line_ending(content, self._settings)
            new_content = _normalize_new_content(new_content, line_ending, path, self._settings)

            if new_content == content:
                return ToolResult(
                    success=False,
                    output="",
                    error="Edit is a no-op; content unchanged",
                )

            diff = generate_unified_diff(content, new_content, str(path))
            git_diff = generate_git_diff(content, new_content, str(path))
            structured = build_structured_diff(content, new_content)

            return build_permission_preview_result(
                f"Ready to replace {replace_count} occurrence(s) in {file_path}",
                {
                    "file_path": str(path),
                    "occurrences_found": match.occurrences,
                    "occurrences_to_replace": replace_count,
                    "matched_text": match.match_text,
                    "diff": diff,
                    "git_diff": git_diff,
                    "structured_diff": structured,
                    "line_ending": line_ending,
                    "new_content": new_content,
                    "encoding": resolve_encoding(encoding, self.default_encoding),
                },
            )

        except Exception as exc:
            return tool_error_result(exc)

    def execute_with_permission(
        self,
        file_path: str,
        new_content: str,
        encoding: str = None,
    ) -> ToolResult:
        """
        Actually execute the edit after permission is granted.

        Args:
            file_path: Path to the file to edit
            new_content: New content to write
            encoding: File encoding

        Returns:
            ToolResult with edit status
        """
        try:
            path = Path(file_path)
            resolved_encoding = resolve_encoding(encoding, self.default_encoding)
            write_text_file(path, new_content, resolved_encoding)
            lsp_notified = False
            if self._file_state_cache:
                self._file_state_cache.snapshot_write(
                    path,
                    new_content,
                    resolved_encoding,
                    line_ending=_resolve_line_ending(new_content, self._settings),
                    updated_by="edit",
                )
            if self._lsp_manager:
                changed = self._lsp_manager.notify_did_change(str(path), new_content)
                saved = self._lsp_manager.notify_did_save(str(path))
                cleared = self._lsp_manager.clear_diagnostics(str(path))
                lsp_notified = changed or saved or cleared

            return ToolResult(
                success=True,
                output=f"Successfully edited {file_path}",
                metadata={
                    "file_path": str(path),
                    "lsp_notified": lsp_notified,
                },
            )

        except Exception as exc:
            return tool_error_result(exc)

    def get_parameters(self) -> Dict[str, Any]:
        """Get tool parameter schema."""
        return build_parameters_schema(
            properties={
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to edit",
                },
                "old_text": {
                    "type": "string",
                    "description": "Text to find and replace",
                },
                "new_text": {
                    "type": "string",
                    "description": "Text to replace with",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences if True",
                    "default": False,
                },
                "encoding": {
                    "type": "string",
                    "description": "File encoding",
                    "default": "utf-8",
                },
            },
            required=["file_path", "old_text", "new_text"],
        )


def _validate_preconditions(
    path: Path,
    cache: Optional[FileStateCache],
    settings: FileToolSettings,
) -> Optional[ToolResult]:
    if settings.enforce_read_before_write:
        if not cache or not cache.has_full_read(path):
            return ToolResult(
                success=False,
                output="",
                error="Edit requires a full ReadTool snapshot first",
            )
    if settings.enforce_mtime_check:
        if not cache:
            return ToolResult(
                success=False,
                output="",
                error="File state cache not available for mtime check",
            )
        state = cache.get_state(path)
        if not state:
            return ToolResult(
                success=False,
                output="",
                error="Missing file state for mtime check",
            )
        if cache.is_modified_since(path, state):
            return ToolResult(
                success=False,
                output="",
                error="File modified since last read; aborting edit",
            )
    return None


def _resolve_line_ending(content: str, settings: FileToolSettings) -> str:
    if settings.preserve_line_endings and content:
        return detect_line_ending(content, _default_line_ending())
    return _default_line_ending()


def _default_line_ending() -> str:
    return get_platform_info().line_ending


def _normalize_new_content(
    content: str,
    line_ending: str,
    path: Path,
    settings: FileToolSettings,
) -> str:
    normalized = normalize_trailing_whitespace(
        content,
        is_markdown=_is_markdown(path),
        enabled=settings.edit_trim_trailing_whitespace,
    )
    if not settings.preserve_line_endings:
        return normalized
    return apply_line_endings(normalized, line_ending)


def _is_markdown(path: Path) -> bool:
    return path.suffix.lower() in {".md", ".markdown"}
