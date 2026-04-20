"""
Tool Execution Helpers
======================

Shared helpers for permission-based execution.
"""

from typing import Any, Dict

from ..core_tool_support.base import ToolResult


def execute_tool_with_permission(
    tool_name: str,
    tool,
    preview_result: ToolResult,
) -> ToolResult:
    """
    Execute the actual operation after permission is granted.
    """
    if not preview_result.metadata:
        return preview_result

    if tool_name == "write" and hasattr(tool, "execute_with_permission"):
        return tool.execute_with_permission(
            file_path=preview_result.metadata.get("file_path"),
            content=preview_result.metadata.get("content"),
            encoding=preview_result.metadata.get("encoding", "utf-8"),
        )
    if tool_name == "edit" and hasattr(tool, "execute_with_permission"):
        return tool.execute_with_permission(
            file_path=preview_result.metadata.get("file_path"),
            new_content=preview_result.metadata.get("new_content"),
            encoding=preview_result.metadata.get("encoding", "utf-8"),
        )
    if tool_name == "bash" and hasattr(tool, "execute_with_permission"):
        return tool.execute_with_permission(
            command=preview_result.metadata.get("command"),
            timeout=preview_result.metadata.get("timeout", 60),
            cwd=preview_result.metadata.get("cwd"),
        )

    return preview_result
