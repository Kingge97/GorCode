"""
File Tool Utilities
===================

Shared helper utilities for file tools.
"""

from __future__ import annotations

from typing import Iterable, List

from .file_constants import (
    BINARY_CHECK_BYTES,
    BINARY_NON_TEXT_RATIO,
    LINE_NUMBER_MIN_WIDTH,
    LINE_NUMBER_SEPARATOR,
)


TEXT_BYTE_WHITELIST = bytes({7, 8, 9, 10, 12, 13, 27})


def detect_line_ending(text: str, default: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    if "\n" in text:
        return "\n"
    return default


def normalize_line_endings(text: str, line_ending: str) -> str:
    if not text:
        return text
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if line_ending == "\n":
        return normalized
    return normalized.replace("\n", line_ending)


def add_line_numbers(lines: Iterable[str], start: int = 1) -> List[str]:
    items = list(lines)
    width = max(LINE_NUMBER_MIN_WIDTH, len(str(start + len(items))))
    numbered: List[str] = []
    for index, line in enumerate(items, start=start):
        numbered.append(f"{str(index).rjust(width)}{LINE_NUMBER_SEPARATOR}{line}")
    return numbered


def is_binary_bytes(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data:
        return True
    sample = data[:BINARY_CHECK_BYTES]
    if not sample:
        return False
    nontext = sum(byte not in TEXT_BYTE_WHITELIST and byte < 32 for byte in sample)
    return nontext / len(sample) > BINARY_NON_TEXT_RATIO
