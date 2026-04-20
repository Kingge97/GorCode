"""
Search path helpers for loaders.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union


@dataclass(frozen=True)
class ResolvedSearchPath:
    """Resolution info for a search path addition."""

    path: Path
    source: Path
    resolution: str  # "direct", "redirect", "symlink"


def add_search_path(
    search_paths: List[Path],
    path: Union[str, Path],
    *,
    encoding: str = "utf-8",
    allow_redirect: bool = False,
    allow_symlink: bool = False,
) -> Optional[ResolvedSearchPath]:
    """
    Add a search path with optional redirect/symlink resolution.

    Args:
        search_paths: List to mutate
        path: Path to add
        encoding: Encoding for redirect file reading
        allow_redirect: Whether to resolve redirect files to directories
        allow_symlink: Whether to resolve symlinked directories

    Returns:
        ResolvedSearchPath if added, otherwise None.
    """
    source = Path(path)
    if not source.exists():
        return None

    resolution = "direct"
    resolved = source

    if source.is_file() and allow_redirect:
        resolved = _resolve_redirect_file(source, encoding)
        if not resolved:
            return None
        resolution = "redirect"
    elif source.is_symlink() and allow_symlink:
        resolved = source.resolve()
        if not (resolved.exists() and resolved.is_dir()):
            return None
        resolution = "symlink"
    elif not source.is_dir():
        return None

    if resolved not in search_paths:
        search_paths.append(resolved)
        return ResolvedSearchPath(path=resolved, source=source, resolution=resolution)

    return None


def _resolve_redirect_file(redirect_file: Path, encoding: str) -> Optional[Path]:
    """
    Resolve a redirect file to its target directory.

    Redirect files contain a relative path to the actual directory.
    """
    try:
        content = redirect_file.read_text(encoding=encoding).strip()
        if not content:
            return None
        target = (redirect_file.parent / content).resolve()
        if target.exists() and target.is_dir():
            return target
    except Exception:
        return None

    return None
