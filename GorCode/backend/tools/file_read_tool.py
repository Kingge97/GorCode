"""
Read Tool
=========

Enhanced file reading with multi-format support and validation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .core_tool_support.base import BaseTool, ToolResult
from .file_tool_support.file_read_helpers import (
    build_text_result,
    check_file_size,
    decode_bytes,
)
from .file_tool_support.file_settings import FileToolSettings
from .file_tool_support.file_state import FileStateCache
from .file_tool_support.file_special_readers import read_image, read_notebook, read_pdf
from .file_tool_support.file_window_read import build_large_window_result
from .file_tool_support.file_utils import is_binary_bytes
from .core_tool_support.path_validation import resolve_and_validate_path
from .core_tool_support.tool_utils import build_parameters_schema, tool_error_result
from ..platform.encoding import EncodingUtils


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


class ReadTool(BaseTool):
    """Tool for reading file contents."""

    name = "read"
    description = "Read the contents of a file. Returns the file content as a string."
    category = "file"
    needs_encoding = True

    def __init__(
        self,
        default_encoding: str = "utf-8",
        file_state_cache: Optional[FileStateCache] = None,
        settings: Optional[FileToolSettings] = None,
    ) -> None:
        super().__init__(default_encoding=default_encoding)
        self._file_state_cache = file_state_cache
        self._settings = settings or FileToolSettings()
        self._encoding_utils = EncodingUtils()

    def execute(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = None,
        encoding: str = None,
        line_numbers: bool = False,
        count_total_lines: bool = False,
    ) -> ToolResult:
        """Read file contents."""
        try:
            path, validation_error = resolve_and_validate_path(file_path, "file")
            if validation_error:
                return validation_error

            if not path:
                return ToolResult(success=False, output="", error="Invalid file path")

            size_error = check_file_size(path, self._settings, check_read_limit=False)
            if size_error:
                return size_error

            return self._read_path(path, offset, limit, encoding, line_numbers, count_total_lines)

        except Exception as exc:
            return tool_error_result(exc)

    def _read_path(
        self,
        path: Path,
        offset: int,
        limit: Optional[int],
        encoding: Optional[str],
        line_numbers: bool,
        count_total_lines: bool,
    ) -> ToolResult:
        extension = path.suffix.lower()
        if extension in IMAGE_EXTENSIONS:
            return read_image(path, self._settings, self._file_state_cache)
        if extension == ".pdf":
            return read_pdf(
                path,
                offset,
                limit,
                line_numbers,
                self._settings,
                self._file_state_cache,
                self.default_encoding,
            )
        if extension == ".ipynb":
            return read_notebook(path, offset, limit, line_numbers, self._settings, self._file_state_cache)
        return self._read_text(path, offset, limit, encoding, line_numbers, count_total_lines)

    def _read_text(
        self,
        path: Path,
        offset: int,
        limit: Optional[int],
        encoding: Optional[str],
        line_numbers: bool,
        count_total_lines: bool,
    ) -> ToolResult:
        size = path.stat().st_size
        if size > self._settings.read_max_bytes:
            return self._read_large_text_window(
                path,
                offset,
                limit,
                encoding,
                line_numbers,
                count_total_lines,
            )
        cached = self._read_cached_text(path, offset, limit, encoding, line_numbers)
        if cached:
            return cached

        data = path.read_bytes()
        if is_binary_bytes(data):
            return ToolResult(
                success=False,
                output="",
                error=f"Binary file detected: {path}",
            )

        content, used_encoding = decode_bytes(data, encoding, self._encoding_utils)
        return build_text_result(
            path,
            content,
            offset,
            limit,
            line_numbers,
            used_encoding,
            deduped=False,
            cache=self._file_state_cache,
            max_tokens=self._settings.read_max_tokens,
        )

    def _read_cached_text(
        self,
        path: Path,
        offset: int,
        limit: Optional[int],
        encoding: Optional[str],
        line_numbers: bool,
    ) -> Optional[ToolResult]:
        if not self._file_state_cache:
            return None
        if not self._file_state_cache.can_use_cached_read(path, offset=offset, limit=limit):
            return None
        cached = self._file_state_cache.get_cached_preview(path)
        if cached is None:
            return None
        return build_text_result(
            path,
            cached,
            offset,
            limit,
            line_numbers,
            encoding or self.default_encoding,
            deduped=True,
            cache=self._file_state_cache,
            max_tokens=self._settings.read_max_tokens,
        )

    def _read_large_text_window(
        self,
        path: Path,
        offset: int,
        limit: Optional[int],
        encoding: Optional[str],
        line_numbers: bool,
        count_total_lines: bool,
    ) -> ToolResult:
        if offset <= 0 and limit is None:
            return check_file_size(path, self._settings, check_read_limit=True)
        return build_large_window_result(
            path,
            offset,
            limit,
            line_numbers,
            encoding or self.default_encoding,
            cache=self._file_state_cache,
            max_tokens=self._settings.read_max_tokens,
            count_total_lines=count_total_lines,
        )

    def get_parameters(self) -> Dict[str, Any]:
        """Get tool parameter schema."""
        return build_parameters_schema(
            properties={
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to read",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line offset to start reading from (0-indexed)",
                    "default": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read",
                },
                "encoding": {
                    "type": "string",
                    "description": "File encoding",
                    "default": "utf-8",
                },
                "line_numbers": {
                    "type": "boolean",
                    "description": "Whether to include line numbers",
                    "default": False,
                },
                "count_total_lines": {
                    "type": "boolean",
                    "description": "Count total lines during partial large-file reads",
                    "default": False,
                },
            },
            required=["file_path"],
        )
