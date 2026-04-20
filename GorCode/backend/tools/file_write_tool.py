"""
Write Tool
==========

Write file contents with permission preview.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .core_tool_support.base import BaseTool, ToolResult
from .file_tool_support.file_diff import build_structured_diff, generate_git_diff, generate_unified_diff
from .file_tool_support.file_io import write_text_file
from .file_tool_support.file_settings import FileToolSettings
from .file_tool_support.file_state import FileStateCache
from .file_tool_support.file_utils import detect_line_ending, normalize_line_endings
from .core_tool_support.tool_utils import (
    build_parameters_schema,
    build_permission_preview_result,
    resolve_encoding,
    tool_error_result,
)
from ..lsp import LspManager
from ..platform.detector import get_platform_info


class WriteTool(BaseTool):
    """Tool for writing content to a file."""

    name = "write"
    description = "Write content to a file. Creates the file if it doesn't exist, overwrites if it does."
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
        content: str,
        encoding: str = None,
    ) -> ToolResult:
        """
        Write content to file.

        Args:
            file_path: Path to the file to write
            content: Content to write to the file
            encoding: File encoding

        Returns:
            ToolResult with write status and permission metadata
        """
        try:
            path = Path(file_path)
            file_exists = path.exists()

            precheck_error = _validate_preconditions(
                path,
                file_exists,
                self._file_state_cache,
                self._settings,
            )
            if precheck_error:
                return precheck_error

            old_content, _ = _read_existing_content(path, encoding, self.default_encoding)
            line_ending = _resolve_line_ending(old_content, self._settings)
            normalized_content = _normalize_content(content, line_ending, self._settings)

            diff = generate_unified_diff(old_content, normalized_content, str(path))
            git_diff = generate_git_diff(old_content, normalized_content, str(path))
            structured = build_structured_diff(old_content, normalized_content)

            return build_permission_preview_result(
                f"Ready to write {len(normalized_content)} characters to {file_path}",
                {
                    "file_path": str(path),
                    "chars_to_write": len(normalized_content),
                    "file_exists": file_exists,
                    "diff": diff,
                    "git_diff": git_diff,
                    "structured_diff": structured,
                    "line_ending": line_ending,
                    "content": normalized_content,
                    "encoding": resolve_encoding(encoding, self.default_encoding),
                },
            )

        except Exception as exc:
            return tool_error_result(exc)

    def execute_with_permission(
        self,
        file_path: str,
        content: str,
        encoding: str = None,
    ) -> ToolResult:
        """
        Actually execute the write after permission is granted.

        Args:
            file_path: Path to the file to write
            content: Content to write to the file
            encoding: File encoding

        Returns:
            ToolResult with write status
        """
        try:
            path = Path(file_path)
            resolved_encoding = resolve_encoding(encoding, self.default_encoding)
            write_text_file(path, content, resolved_encoding, create_parents=True)
            lsp_notified = False
            if self._file_state_cache:
                self._file_state_cache.snapshot_write(
                    path,
                    content,
                    resolved_encoding,
                    line_ending=_resolve_line_ending(content, self._settings),
                    updated_by="write",
                )
            if self._lsp_manager:
                changed = self._lsp_manager.notify_did_change(str(path), content)
                saved = self._lsp_manager.notify_did_save(str(path))
                cleared = self._lsp_manager.clear_diagnostics(str(path))
                lsp_notified = changed or saved or cleared

            return ToolResult(
                success=True,
                output=f"Successfully wrote {len(content)} characters to {file_path}",
                metadata={
                    "file_path": str(path),
                    "chars_written": len(content),
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
                    "description": "Path to the file to write",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
                "encoding": {
                    "type": "string",
                    "description": "File encoding",
                    "default": "utf-8",
                },
            },
            required=["file_path", "content"],
        )


def _read_existing_content(
    path: Path,
    encoding: Optional[str],
    default_encoding: str,
) -> tuple[str, bool]:
    file_exists = path.exists()
    if not file_exists:
        return "", False
    try:
        resolved = resolve_encoding(encoding, default_encoding)
        return path.read_text(encoding=resolved), True
    except Exception:
        return "(unable to read existing file)", True


def _validate_preconditions(
    path: Path,
    file_exists: bool,
    cache: Optional[FileStateCache],
    settings: FileToolSettings,
) -> Optional[ToolResult]:
    if not file_exists:
        return None
    if settings.enforce_read_before_write:
        if not cache or not cache.has_full_read(path):
            return ToolResult(
                success=False,
                output="",
                error="Write requires a full ReadTool snapshot first",
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
                error="File modified since last read; aborting write",
            )
    return None


def _resolve_line_ending(old_content: str, settings: FileToolSettings) -> str:
    if settings.preserve_line_endings and old_content:
        return detect_line_ending(old_content, _default_line_ending())
    return _default_line_ending()


def _default_line_ending() -> str:
    return get_platform_info().line_ending


def _normalize_content(content: str, line_ending: str, settings: FileToolSettings) -> str:
    if not settings.preserve_line_endings:
        return content
    return normalize_line_endings(content, line_ending)
