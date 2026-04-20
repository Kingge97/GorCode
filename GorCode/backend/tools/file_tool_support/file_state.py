"""
File State Cache
================

Tracks file read/write state for validation and deduplication.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
import hashlib
import time

from .file_constants import DEFAULT_MAX_CACHE_CONTENT_CHARS


@dataclass(frozen=True)
class FileState:
    """Immutable snapshot of file state."""

    path: str
    mtime: float
    size: int
    content_hash: str
    encoding: str
    is_partial: bool
    offset: int
    limit: Optional[int]
    line_ending: str
    updated_by: str
    updated_at: float
    content_preview: Optional[str]
    content_is_full: bool


class FileStateCache:
    """Cache for file state snapshots."""

    def __init__(self, max_preview_chars: int = DEFAULT_MAX_CACHE_CONTENT_CHARS) -> None:
        self._states: Dict[str, FileState] = {}
        self._max_preview_chars = max_preview_chars

    def get_state(self, path: Path) -> Optional[FileState]:
        return self._states.get(str(path))

    def snapshot_read(
        self,
        path: Path,
        content: str,
        encoding: str,
        *,
        is_partial: bool,
        offset: int,
        limit: Optional[int],
        line_ending: str,
    ) -> FileState:
        state = self._build_state(
            path,
            content,
            encoding,
            is_partial=is_partial,
            offset=offset,
            limit=limit,
            line_ending=line_ending,
            updated_by="read",
        )
        self._states[state.path] = state
        return state

    def snapshot_write(
        self,
        path: Path,
        content: str,
        encoding: str,
        *,
        line_ending: str,
        updated_by: str,
    ) -> FileState:
        state = self._build_state(
            path,
            content,
            encoding,
            is_partial=False,
            offset=0,
            limit=None,
            line_ending=line_ending,
            updated_by=updated_by,
        )
        self._states[state.path] = state
        return state

    def snapshot_bytes(
        self,
        path: Path,
        data: bytes,
        *,
        updated_by: str,
    ) -> FileState:
        state = self._build_binary_state(
            path,
            data,
            updated_by=updated_by,
        )
        self._states[state.path] = state
        return state

    def has_full_read(self, path: Path) -> bool:
        state = self.get_state(path)
        if not state:
            return False
        return state.updated_by == "read" and not state.is_partial

    def is_modified_since(self, path: Path, state: FileState) -> bool:
        stat = path.stat()
        if stat.st_mtime != state.mtime:
            return True
        return stat.st_size != state.size

    def can_use_cached_read(
        self,
        path: Path,
        *,
        offset: int,
        limit: Optional[int],
    ) -> bool:
        state = self.get_state(path)
        if not state or state.updated_by != "read":
            return False
        if state.is_partial and (state.offset != offset or state.limit != limit):
            return False
        if not state.is_partial and (offset != 0 or limit is not None):
            return False
        return not self.is_modified_since(path, state)

    def get_cached_preview(self, path: Path) -> Optional[str]:
        state = self.get_state(path)
        if not state:
            return None
        if not state.content_is_full:
            return None
        return state.content_preview

    def _build_state(
        self,
        path: Path,
        content: str,
        encoding: str,
        *,
        is_partial: bool,
        offset: int,
        limit: Optional[int],
        line_ending: str,
        updated_by: str,
    ) -> FileState:
        stat = path.stat()
        content_hash = _hash_text(content, encoding)
        preview, is_full = _trim_preview(content, self._max_preview_chars)
        return FileState(
            path=str(path),
            mtime=stat.st_mtime,
            size=stat.st_size,
            content_hash=content_hash,
            encoding=encoding,
            is_partial=is_partial,
            offset=offset,
            limit=limit,
            line_ending=line_ending,
            updated_by=updated_by,
            updated_at=time.time(),
            content_preview=preview,
            content_is_full=is_full,
        )

    def _build_binary_state(
        self,
        path: Path,
        data: bytes,
        *,
        updated_by: str,
    ) -> FileState:
        stat = path.stat()
        content_hash = _hash_bytes(data)
        return FileState(
            path=str(path),
            mtime=stat.st_mtime,
            size=stat.st_size,
            content_hash=content_hash,
            encoding="binary",
            is_partial=False,
            offset=0,
            limit=None,
            line_ending="",
            updated_by=updated_by,
            updated_at=time.time(),
            content_preview=None,
            content_is_full=False,
        )


def _hash_text(text: str, encoding: str) -> str:
    data = text.encode(encoding, errors="replace")
    return hashlib.sha256(data).hexdigest()


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _trim_preview(text: str, max_chars: int) -> tuple[Optional[str], bool]:
    if not text:
        return "", True
    if len(text) <= max_chars:
        return text, True
    return text[:max_chars], False
