"""
Read Tool Helpers
=================

Helper functions for the ReadTool implementation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import json

from ..core_tool_support.base import ToolResult
from .file_state import FileStateCache
from .file_utils import add_line_numbers, detect_line_ending
from .file_constants import MIN_PDF_PAGE_COUNT
from .file_settings import FileToolSettings
from ..core_tool_support.tool_utils import truncate_output
from ...context import TokenEstimator
from ...platform.encoding import EncodingUtils


def check_file_size(
    path: Path,
    settings: FileToolSettings,
    *,
    check_read_limit: bool,
) -> Optional[ToolResult]:
    size = path.stat().st_size
    if size > settings.max_file_bytes:
        return ToolResult(
            success=False,
            output="",
            error=f"File exceeds maximum size: {size} bytes",
        )
    if check_read_limit and size > settings.read_max_bytes:
        return ToolResult(
            success=False,
            output="",
            error=(
                f"File too large for read ({size} bytes). "
                "Use offset/limit or increase file_read_max_bytes."
            ),
        )
    return None


def decode_bytes(
    data: bytes,
    encoding: Optional[str],
    utils: EncodingUtils,
) -> tuple[str, str]:
    if encoding:
        try:
            return data.decode(encoding), encoding
        except Exception:
            pass
    text, used = utils.safe_decode(data)
    return text, used


def build_text_result(
    path: Path,
    content: str,
    offset: int,
    limit: Optional[int],
    line_numbers: bool,
    encoding: str,
    *,
    deduped: bool,
    cache: Optional[FileStateCache],
    max_tokens: int,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> ToolResult:
    lines = content.splitlines()
    total_lines = len(lines)
    sliced = slice_lines(lines, offset, limit)
    if line_numbers:
        sliced = add_line_numbers(sliced, start=offset + 1)
    result_text = "\n".join(sliced)
    token_limit_error = check_token_limit(result_text, max_tokens)
    if token_limit_error:
        return token_limit_error

    result_text = truncate_output(result_text)

    line_ending = detect_line_ending(content, "\n")
    is_partial = offset > 0 or limit is not None
    modified_since_last_read = False
    if cache:
        previous_state = cache.get_state(path)
        if previous_state:
            modified_since_last_read = cache.is_modified_since(path, previous_state)
    if cache:
        cache.snapshot_read(
            path,
            content,
            encoding,
            is_partial=is_partial,
            offset=offset,
            limit=limit,
            line_ending=line_ending,
        )

    metadata = {
        "file_path": str(path),
        "total_lines": total_lines,
        "returned_lines": len(sliced),
        "encoding": encoding,
        "line_numbers": line_numbers,
        "deduped": deduped,
        "is_partial_view": is_partial,
        "modified_since_last_read": modified_since_last_read,
    }
    if extra_metadata:
        metadata.update(extra_metadata)

    return ToolResult(success=True, output=result_text, metadata=metadata)


def slice_lines(lines: List[str], offset: int, limit: Optional[int]) -> List[str]:
    if offset > 0:
        lines = lines[offset:]
    if limit is not None and limit > 0:
        return lines[:limit]
    return lines


def check_token_limit(text: str, max_tokens: int) -> Optional[ToolResult]:
    if max_tokens <= 0:
        return None
    token_count = TokenEstimator.estimate_text(text)
    if token_count > 0 and token_count > max_tokens:
        return ToolResult(
            success=False,
            output="",
            error=f"Read output exceeds token limit: {token_count}",
        )
    return None


def image_mime_type(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "application/octet-stream")


def extract_pdf_pages(path: Path) -> List[str]:
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise RuntimeError("pypdf is required for PDF reading") from exc

    reader = PdfReader(str(path))
    pages: List[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return pages


def join_pages(pages: List[str], start_index: int) -> str:
    segments = []
    for index, content in enumerate(pages, start=start_index + 1):
        segments.append(f"[Page {index}]\n{content}")
    return "\n\n".join(segments)


def validate_pdf_page_limit(total_pages: int, settings: FileToolSettings, limit: Optional[int]) -> Optional[ToolResult]:
    if total_pages > max(settings.pdf_max_pages, MIN_PDF_PAGE_COUNT) and not limit:
        return ToolResult(
            success=False,
            output="",
            error=(
                f"PDF too large ({total_pages} pages). "
                "Use limit to read a subset."
            ),
        )
    return None


def extract_notebook_text(raw_json: str) -> str:
    data = json.loads(raw_json)
    cells = data.get("cells", [])
    segments = []
    for index, cell in enumerate(cells, start=1):
        cell_type = cell.get("cell_type", "unknown")
        segments.append(f"[Cell {index}] {cell_type}")
        source = cell.get("source", [])
        if isinstance(source, list):
            segments.extend([line.rstrip("\n") for line in source])
        else:
            segments.append(str(source))
        segments.append("")
    return "\n".join(segments).strip()
