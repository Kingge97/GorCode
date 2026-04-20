"""
Read Tool
=========

Enhanced file reading with multi-format support and validation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import base64

from .core_tool_support.base import BaseTool, ToolResult
from .file_tool_support.file_read_helpers import (
    build_text_result,
    check_file_size,
    decode_bytes,
    extract_notebook_text,
    extract_pdf_pages,
    image_mime_type,
    join_pages,
    validate_pdf_page_limit,
)
from .file_tool_support.file_settings import FileToolSettings
from .file_tool_support.file_state import FileStateCache
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
    ) -> ToolResult:
        """
        Read file contents.

        Args:
            file_path: Path to the file to read
            offset: Line offset to start reading from (0-indexed)
            limit: Maximum number of lines to read
            encoding: File encoding
            line_numbers: Whether to include line numbers

        Returns:
            ToolResult with file contents
        """
        try:
            path, validation_error = resolve_and_validate_path(file_path, "file")
            if validation_error:
                return validation_error

            if not path:
                return ToolResult(success=False, output="", error="Invalid file path")

            size_error = check_file_size(path, self._settings, check_read_limit=False)
            if size_error:
                return size_error

            extension = path.suffix.lower()
            if extension in IMAGE_EXTENSIONS:
                return self._read_image(path)
            if extension == ".pdf":
                return self._read_pdf(path, offset, limit, line_numbers)
            if extension == ".ipynb":
                return self._read_notebook(path, offset, limit, line_numbers)

            return self._read_text(path, offset, limit, encoding, line_numbers)

        except Exception as exc:
            return tool_error_result(exc)

    def _read_text(
        self,
        path: Path,
        offset: int,
        limit: Optional[int],
        encoding: Optional[str],
        line_numbers: bool,
    ) -> ToolResult:
        size_error = check_file_size(path, self._settings, check_read_limit=True)
        if size_error:
            return size_error
        if self._file_state_cache and self._file_state_cache.can_use_cached_read(
            path,
            offset=offset,
            limit=limit,
        ):
            cached = self._file_state_cache.get_cached_preview(path)
            if cached is not None:
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

    def _read_image(self, path: Path) -> ToolResult:
        if not self._settings.enable_images:
            return ToolResult(success=False, output="", error="Image reading is disabled")
        size = path.stat().st_size
        if size > self._settings.image_max_bytes:
            return ToolResult(
                success=False,
                output="",
                error=f"Image exceeds max size: {size} bytes",
            )
        data = path.read_bytes()
        mime = image_mime_type(path)
        encoded = base64.b64encode(data).decode("ascii")
        data_url = f"data:{mime};base64,{encoded}"
        if self._file_state_cache:
            self._file_state_cache.snapshot_bytes(path, data, updated_by="read")
        return ToolResult(
            success=True,
            output="[image]",
            metadata={
                "file_path": str(path),
                "content_type": "image",
                "result_object": [
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    }
                ],
            },
        )

    def _read_pdf(
        self,
        path: Path,
        offset: int,
        limit: Optional[int],
        line_numbers: bool,
    ) -> ToolResult:
        if not self._settings.enable_pdf:
            return ToolResult(success=False, output="", error="PDF reading is disabled")
        pages = extract_pdf_pages(path)
        total_pages = len(pages)
        if total_pages == 0:
            return ToolResult(success=False, output="", error="PDF contains no pages")
        limit_error = validate_pdf_page_limit(total_pages, self._settings, limit)
        if limit_error:
            return limit_error

        start = max(offset, 0)
        end = total_pages if limit is None else min(total_pages, start + max(limit, 0))
        selected = pages[start:end]
        content = join_pages(selected, start)
        return build_text_result(
            path,
            content,
            0,
            None,
            line_numbers,
            self.default_encoding,
            deduped=False,
            cache=self._file_state_cache,
            max_tokens=self._settings.read_max_tokens,
            extra_metadata={
                "total_pages": total_pages,
                "returned_pages": len(selected),
                "page_offset": start,
            },
        )

    def _read_notebook(
        self,
        path: Path,
        offset: int,
        limit: Optional[int],
        line_numbers: bool,
    ) -> ToolResult:
        if not self._settings.enable_notebook:
            return ToolResult(success=False, output="", error="Notebook reading is disabled")
        data = path.read_text(encoding="utf-8")
        content = extract_notebook_text(data)
        return build_text_result(
            path,
            content,
            offset,
            limit,
            line_numbers,
            "utf-8",
            deduped=False,
            cache=self._file_state_cache,
            max_tokens=self._settings.read_max_tokens,
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
            },
            required=["file_path"],
        )
