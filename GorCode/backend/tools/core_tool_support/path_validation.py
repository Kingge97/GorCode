"""
Shared path validation helpers for tools.
"""

from pathlib import Path
from typing import List, Optional, Tuple
import difflib

from .base import ToolResult
from ...platform.detector import PlatformDetector


BLOCKED_DEVICE_PATHS = {
    "/dev/zero",
    "/dev/random",
    "/dev/urandom",
    "/dev/null",
}

MACOS_SPACE_VARIANTS = ["\u00A0", "\u202F", "\u2007", "\u2009"]


def validate_path(path: Path, kind: str, original_value: Optional[str] = None) -> Optional[ToolResult]:
    """
    Validate a path and return a ToolResult error if invalid.

    Args:
        path: Path to validate
        kind: "file", "dir", or "path"
        original_value: Original string path for messaging
    """
    if kind == "file":
        if not path.exists():
            return _build_not_found_error(path, "File", original_value)
        if not path.is_file():
            return ToolResult(success=False, output="", error=f"Not a file: {path}")
        return None

    if kind == "dir":
        if not path.exists():
            return _build_not_found_error(path, "Directory", original_value)
        if not path.is_dir():
            return ToolResult(success=False, output="", error=f"Not a directory: {path}")
        return None

    if kind == "path":
        if not path.exists():
            return _build_not_found_error(path, "Path", original_value)
        return None

    raise ValueError(f"Unsupported path kind: {kind}")


def resolve_and_validate_path(path_value: str, kind: str) -> Tuple[Optional[Path], Optional[ToolResult]]:
    """
    Build a Path from a string and validate it.

    Returns:
        (path, error). If error is not None, path will be None.
    """
    if _is_blocked_device_path(path_value):
        return None, ToolResult(
            success=False,
            output="",
            error=f"Blocked device path: {path_value}",
        )

    path = Path(path_value)
    normalized = _normalize_macos_path(path)
    validation_error = validate_path(normalized, kind, original_value=path_value)
    if validation_error:
        return None, validation_error
    return normalized, None


def _normalize_macos_path(path: Path) -> Path:
    detector = PlatformDetector()
    if not detector.is_macos:
        return path
    if path.exists():
        return path
    path_str = str(path)
    if not any(variant in path_str for variant in MACOS_SPACE_VARIANTS):
        return path
    normalized = path_str
    for variant in MACOS_SPACE_VARIANTS:
        normalized = normalized.replace(variant, " ")
    candidate = Path(normalized)
    return candidate if candidate.exists() else path


def _is_blocked_device_path(path_value: str) -> bool:
    if not path_value:
        return False
    normalized = path_value.replace("\\", "/")
    return normalized in BLOCKED_DEVICE_PATHS or normalized.startswith("/dev/")


def _build_not_found_error(path: Path, label: str, original_value: Optional[str]) -> ToolResult:
    suggestions = _suggest_similar_paths(path)
    original = original_value or str(path)
    if suggestions:
        hint = "; ".join(suggestions)
        message = f"{label} not found: {original}. Did you mean: {hint}"
    else:
        message = f"{label} not found: {original}"
    return ToolResult(success=False, output="", error=message)


def _suggest_similar_paths(path: Path) -> List[str]:
    parent = path.parent if path.parent.exists() else None
    if not parent:
        return []
    try:
        candidates = [item.name for item in parent.iterdir()]
    except Exception:
        return []
    matches = difflib.get_close_matches(path.name, candidates, n=3, cutoff=0.6)
    return [str(parent / match) for match in matches]
