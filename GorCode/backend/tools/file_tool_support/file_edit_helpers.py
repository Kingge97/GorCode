"""
Edit Tool Helpers
=================

Helper utilities for EditTool behaviors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional
import re

from .file_settings import FileToolSettings
from .file_utils import normalize_line_endings

MARKDOWN_LINEBREAK = "  "


@dataclass(frozen=True)
class MatchResult:
    match_text: str
    occurrences: int


def maybe_deserialize(text: str, enabled: bool) -> str:
    if not enabled:
        return text
    if _needs_unescape(text):
        try:
            return bytes(text, "utf-8").decode("unicode_escape")
        except Exception:
            return text
    return text


def find_match_text(
    content: str,
    old_text: str,
    settings: FileToolSettings,
) -> Optional[MatchResult]:
    candidates = _build_candidates(old_text, settings)
    for candidate in candidates:
        if candidate and candidate in content:
            return MatchResult(candidate, content.count(candidate))
    if settings.edit_smart_find:
        for candidate in candidates:
            match = _find_whitespace_insensitive_match(content, candidate)
            if match:
                return match
    return None


def normalize_trailing_whitespace(
    content: str,
    *,
    is_markdown: bool,
    enabled: bool,
) -> str:
    if not enabled:
        return content
    lines = content.splitlines()
    normalized = [_normalize_line(line, is_markdown) for line in lines]
    return "\n".join(normalized)


def apply_line_endings(content: str, line_ending: str) -> str:
    return normalize_line_endings(content, line_ending)


def _build_candidates(text: str, settings: FileToolSettings) -> list[str]:
    if not (settings.edit_smart_find or settings.edit_quote_normalization):
        return [text]
    normalized = normalize_quotes(text)
    curly = _to_curly_quotes(text)
    return _unique_candidates([text, normalized, curly])


def normalize_quotes(text: str) -> str:
    return (
        text.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )


def _to_curly_quotes(text: str) -> str:
    return text.replace('"', "\u201d").replace("'", "\u2019")


def _unique_candidates(candidates: Iterable[str]) -> list[str]:
    seen = set()
    unique = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique


def _find_whitespace_insensitive_match(
    content: str,
    text: str,
) -> Optional[MatchResult]:
    if not text:
        return None
    if not _should_try_whitespace_match(text):
        return None
    pattern = _build_whitespace_pattern(text)
    try:
        regex = re.compile(pattern, re.DOTALL)
    except re.error:
        return None
    matches = list(regex.finditer(content))
    if not matches:
        return None
    return MatchResult(matches[0].group(0), len(matches))


def _should_try_whitespace_match(text: str) -> bool:
    if not any(ch.isspace() for ch in text):
        return False
    non_ws = sum(1 for ch in text if not ch.isspace())
    return non_ws >= 6


def _build_whitespace_pattern(text: str) -> str:
    parts = []
    i = 0
    length = len(text)
    while i < length:
        ch = text[i]
        if ch.isspace():
            while i < length and text[i].isspace():
                i += 1
            parts.append(r"\s+")
            continue
        parts.append(re.escape(ch))
        i += 1
    return "".join(parts)


def _needs_unescape(text: str) -> bool:
    return any(token in text for token in ("\\n", "\\t", "\\r", "\\\\"))


def _normalize_line(line: str, is_markdown: bool) -> str:
    if is_markdown and line.endswith(MARKDOWN_LINEBREAK):
        stripped = line.rstrip()
        return stripped + MARKDOWN_LINEBREAK
    return line.rstrip()
