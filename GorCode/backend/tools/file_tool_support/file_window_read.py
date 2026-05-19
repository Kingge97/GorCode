"""
Large file window reading helpers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..core_tool_support.base import ToolResult
from ..core_tool_support.tool_utils import truncate_output
from .file_constants import BINARY_CHECK_BYTES
from .file_state import FileStateCache
from .file_utils import add_line_numbers, detect_line_ending, is_binary_bytes
from ...context import TokenEstimator


def build_large_window_result(
    path: Path,
    offset: int,
    limit: Optional[int],
    line_numbers: bool,
    encoding: str,
    *,
    cache: Optional[FileStateCache],
    max_tokens: int,
    count_total_lines: bool,
) -> ToolResult:
    if limit is None or limit <= 0:
        return ToolResult(
            success=False,
            output="",
            error="Large file partial read requires a positive limit.",
        )
    binary_error = check_binary_sample(path)
    if binary_error:
        return binary_error
    try:
        window, total_lines = read_line_window(path, offset, limit, encoding, count_total_lines)
    except UnicodeError:
        return ToolResult(
            success=False,
            output="",
            error=f"Failed to decode large file window with encoding: {encoding}",
        )
    return build_window_result(
        path,
        window,
        offset,
        line_numbers,
        encoding,
        cache=cache,
        max_tokens=max_tokens,
        total_lines=total_lines,
    )


def check_binary_sample(path: Path) -> Optional[ToolResult]:
    with path.open("rb") as handle:
        sample = handle.read(BINARY_CHECK_BYTES)
    if is_binary_bytes(sample):
        return ToolResult(success=False, output="", error=f"Binary file detected: {path}")
    return None


def read_line_window(
    path: Path,
    offset: int,
    limit: int,
    encoding: str,
    count_total_lines: bool,
) -> tuple[list[str], Optional[int]]:
    start = max(offset, 0)
    stop = start + limit
    window: list[str] = []
    total_lines = 0
    with path.open("r", encoding=encoding, newline="") as handle:
        for index, raw_line in enumerate(handle):
            total_lines = index + 1
            if start <= index < stop:
                window.append(raw_line.rstrip("\r\n"))
            if index >= stop - 1 and not count_total_lines:
                return window, None
    return window, total_lines if count_total_lines else None


def build_window_result(
    path: Path,
    window: list[str],
    offset: int,
    line_numbers: bool,
    encoding: str,
    *,
    cache: Optional[FileStateCache],
    max_tokens: int,
    total_lines: Optional[int],
) -> ToolResult:
    result_lines = add_line_numbers(window, start=offset + 1) if line_numbers else window
    result_text = "\n".join(result_lines)
    token_limit_error = check_token_limit(result_text, max_tokens)
    if token_limit_error:
        return token_limit_error
    snapshot_text = "\n".join(window)
    line_ending = detect_line_ending(snapshot_text, "\n")
    modified = snapshot_window(cache, path, snapshot_text, offset, encoding, line_ending)
    return ToolResult(
        success=True,
        output=truncate_output(result_text),
        metadata={
            "file_path": str(path),
            "total_lines": total_lines,
            "total_lines_known": total_lines is not None,
            "returned_lines": len(window),
            "encoding": encoding,
            "line_numbers": line_numbers,
            "deduped": False,
            "is_partial_view": True,
            "modified_since_last_read": modified,
        },
    )


def check_token_limit(text: str, max_tokens: int) -> Optional[ToolResult]:
    if max_tokens <= 0:
        return None
    token_count = TokenEstimator.estimate_text(text)
    if token_count > 0 and token_count > max_tokens:
        return ToolResult(success=False, output="", error=f"Read output exceeds token limit: {token_count}")
    return None


def snapshot_window(
    cache: Optional[FileStateCache],
    path: Path,
    text: str,
    offset: int,
    encoding: str,
    line_ending: str,
) -> bool:
    modified = False
    if cache:
        previous_state = cache.get_state(path)
        if previous_state:
            modified = cache.is_modified_since(path, previous_state)
        cache.snapshot_read(
            path,
            text,
            encoding,
            is_partial=True,
            offset=offset,
            limit=len(text.splitlines()),
            line_ending=line_ending,
        )
    return modified
