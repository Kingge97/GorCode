"""
Specialized readers for non-plain-text file types.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import base64

from ..core_tool_support.base import ToolResult
from .file_read_helpers import (
    build_text_result,
    extract_notebook_text,
    extract_pdf_pages,
    image_mime_type,
    join_pages,
    validate_pdf_page_limit,
)
from .file_settings import FileToolSettings
from .file_state import FileStateCache


def read_image(
    path: Path,
    settings: FileToolSettings,
    cache: Optional[FileStateCache],
) -> ToolResult:
    if not settings.enable_images:
        return ToolResult(success=False, output="", error="Image reading is disabled")
    size = path.stat().st_size
    if size > settings.image_max_bytes:
        return ToolResult(success=False, output="", error=f"Image exceeds max size: {size} bytes")
    data = path.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    if cache:
        cache.snapshot_bytes(path, data, updated_by="read")
    return ToolResult(
        success=True,
        output="[image]",
        metadata={
            "file_path": str(path),
            "content_type": "image",
            "result_object": [
                {"type": "image_url", "image_url": {"url": f"data:{image_mime_type(path)};base64,{encoded}"}}
            ],
        },
    )


def read_pdf(
    path: Path,
    offset: int,
    limit: Optional[int],
    line_numbers: bool,
    settings: FileToolSettings,
    cache: Optional[FileStateCache],
    default_encoding: str,
) -> ToolResult:
    if not settings.enable_pdf:
        return ToolResult(success=False, output="", error="PDF reading is disabled")
    pages = extract_pdf_pages(path)
    total_pages = len(pages)
    if total_pages == 0:
        return ToolResult(success=False, output="", error="PDF contains no pages")
    limit_error = validate_pdf_page_limit(total_pages, settings, limit)
    if limit_error:
        return limit_error
    start = max(offset, 0)
    end = total_pages if limit is None else min(total_pages, start + max(limit, 0))
    return build_text_result(
        path,
        join_pages(pages[start:end], start),
        0,
        None,
        line_numbers,
        default_encoding,
        deduped=False,
        cache=cache,
        max_tokens=settings.read_max_tokens,
        extra_metadata={"total_pages": total_pages, "returned_pages": end - start, "page_offset": start},
    )


def read_notebook(
    path: Path,
    offset: int,
    limit: Optional[int],
    line_numbers: bool,
    settings: FileToolSettings,
    cache: Optional[FileStateCache],
) -> ToolResult:
    if not settings.enable_notebook:
        return ToolResult(success=False, output="", error="Notebook reading is disabled")
    content = extract_notebook_text(path.read_text(encoding="utf-8"))
    return build_text_result(
        path,
        content,
        offset,
        limit,
        line_numbers,
        "utf-8",
        deduped=False,
        cache=cache,
        max_tokens=settings.read_max_tokens,
    )
