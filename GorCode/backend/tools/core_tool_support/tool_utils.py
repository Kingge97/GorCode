"""
Shared tool helpers to reduce boilerplate across tool implementations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .base import ToolResult


DEFAULT_MAX_OUTPUT_CHARS = 50000
TRUNCATED_SUFFIX = "\n... (truncated)"


def resolve_encoding(requested: Optional[str], default: str) -> str:
    """
    Resolve a requested encoding to a concrete encoding value.
    """
    return requested or default


def truncate_output(
    text: Optional[str],
    max_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
    suffix: str = TRUNCATED_SUFFIX,
) -> str:
    """
    Truncate output to a maximum number of characters with a suffix.
    """
    if not text:
        return text or ""
    if len(text) > max_chars:
        return text[:max_chars] + suffix
    return text


def tool_error_result(
    error: Exception,
    *,
    prefix: Optional[str] = None,
    output: str = "",
) -> ToolResult:
    """
    Standardize error ToolResult creation.
    """
    from .base import ToolResult
    message = str(error)
    if prefix:
        message = f"{prefix}{message}"
    return ToolResult(success=False, output=output, error=message)


def build_permission_preview_result(message: str, metadata: Dict[str, Any]) -> ToolResult:
    """
    Standardize preview results that require a permission prompt.
    """
    from .base import ToolResult
    merged = dict(metadata)
    merged["requires_permission"] = True
    return ToolResult(success=True, output=message, metadata=merged)


def build_parameters_schema(
    properties: Dict[str, Any],
    required: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Build a standard JSON schema wrapper for tool parameters.
    """
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required) if required else [],
    }
