"""
Convert tool previews into sandbox requests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ..tools.core_tool_support.base import ToolResult
from .types import SandboxRequest


READ_TOOLS = {"read", "ls", "glob", "grep"}
OPERATIONS = {
    "read": "read",
    "ls": "list",
    "glob": "search",
    "grep": "search",
    "write": "write",
    "edit": "edit",
    "bash": "execute",
}


def build_request(
    tool_name: str,
    arguments: Dict[str, Any],
    preview_result: ToolResult,
    workspace_root: Path,
) -> SandboxRequest:
    """Build a sandbox request from tool call context."""
    metadata = dict(preview_result.metadata or {})
    operation = _operation_for(tool_name, metadata)
    cwd = _cwd_from(arguments, metadata, workspace_root)
    return SandboxRequest(
        tool_name=tool_name,
        operation=operation,
        arguments=dict(arguments or {}),
        metadata=metadata,
        workspace_root=Path(workspace_root),
        cwd=cwd,
        tool_result_preview=preview_result,
    )


def _operation_for(tool_name: str, metadata: Dict[str, Any]) -> str:
    explicit = metadata.get("operation")
    if explicit:
        return str(explicit)
    return OPERATIONS.get(tool_name.lower(), "unknown")


def _cwd_from(
    arguments: Dict[str, Any],
    metadata: Dict[str, Any],
    workspace_root: Path,
) -> Optional[Path]:
    cwd = metadata.get("cwd") or arguments.get("cwd")
    if not cwd:
        return Path(workspace_root)
    return Path(str(cwd))


def target_paths_for(request: SandboxRequest) -> list[str]:
    """Return target paths declared by built-in previews or custom metadata."""
    paths = request.metadata.get("target_paths")
    if isinstance(paths, list):
        return [str(path) for path in paths]
    path = request.metadata.get("file_path") or request.metadata.get("path")
    if path:
        return [str(path)]
    argument_path = request.arguments.get("file_path") or request.arguments.get("path")
    return [str(argument_path)] if argument_path else []


def is_known_read_tool(tool_name: str) -> bool:
    """Return true for builtin read-only tools."""
    return tool_name.lower() in READ_TOOLS
