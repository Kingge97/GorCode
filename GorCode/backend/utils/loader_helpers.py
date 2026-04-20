"""
Shared loader helpers for agent/skill discovery and file reads.
"""

from pathlib import Path
from typing import Iterable, Iterator, List, Optional


def iter_existing_search_paths(search_paths: Iterable[Path]) -> Iterator[Path]:
    """
    Yield search paths that exist on disk.
    """
    for search_path in search_paths:
        if search_path.exists():
            yield search_path


def discover_files(search_paths: Iterable[Path], pattern: str) -> List[Path]:
    """
    Discover files matching a glob pattern in search paths.
    """
    discovered: List[Path] = []
    for search_path in iter_existing_search_paths(search_paths):
        for item in search_path.glob(pattern):
            if item.is_file():
                discovered.append(item)
    return discovered


def discover_dirs_with_file(search_paths: Iterable[Path], filename: str) -> List[Path]:
    """
    Discover directories that contain a specific file.
    """
    discovered: List[Path] = []
    for search_path in iter_existing_search_paths(search_paths):
        for item in search_path.iterdir():
            if item.is_dir() and (item / filename).exists():
                discovered.append(item)
    return discovered


def read_text_file(path: Path, encoding: str) -> Optional[str]:
    """
    Read a text file with basic error handling.
    """
    try:
        return path.read_text(encoding=encoding)
    except Exception:
        return None
