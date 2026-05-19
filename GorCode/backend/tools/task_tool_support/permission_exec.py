"""
Shared permission execution helpers for tools.
"""

from typing import Any, Dict, Optional, Tuple

from ...permission import PermissionManager, PermissionType
from ...permission.utils import get_permission_type, request_permission_sync
from ...sandbox import decision_to_tool_result, protocol_error_result
from ...sandbox.types import SandboxProtocolError
from ..core_tool_support.base import ToolResult
from .tool_execution import execute_tool_with_permission


def _requires_permission(tool: Any, result: ToolResult) -> bool:
    """
    Check whether a tool execution result requires a permission prompt.
    """
    return bool(
        tool
        and getattr(tool, "requires_permission", False)
        and result.metadata
        and result.metadata.get("requires_permission")
    )


def get_permission_request(
    tool_name: str,
    tool: Any,
    result: ToolResult,
    permission_manager: Optional[PermissionManager],
) -> Optional[PermissionType]:
    """
    Determine if a permission prompt is required for this tool execution.
    """
    if not _requires_permission(tool, result):
        return None

    if permission_manager is None:
        return None

    permission_type = get_permission_type(tool_name, result.metadata)
    if not permission_type:
        return None

    if not permission_manager.should_prompt(tool_name, permission_type, result.metadata):
        return None

    return permission_type


def execute_with_permissions(
    tool_name: str,
    tool: Any,
    result: ToolResult,
    permission_manager: Optional[PermissionManager],
    permission_callback,
    *,
    sandbox_manager=None,
    arguments: Optional[Dict[str, Any]] = None,
) -> Tuple[ToolResult, bool]:
    """
    Execute a tool after handling permission checks.

    Returns:
        (tool_result, rejected_without_reason)
    """
    sandbox_result = evaluate_sandbox(
        tool_name,
        result,
        sandbox_manager=sandbox_manager,
        arguments=arguments,
    )
    if sandbox_result:
        return sandbox_result, False

    if not _requires_permission(tool, result):
        return result, False

    permission_type = get_permission_type(tool_name, result.metadata)
    if not permission_type:
        return result, False

    granted, error_msg, rejected_without_reason = request_permission_sync(
        permission_manager,
        permission_callback,
        permission_type,
        result.metadata,
        tool_name=tool_name,
    )
    if not granted:
        return ToolResult(success=False, output="", error=error_msg), rejected_without_reason

    # Permission granted - execute actual operation
    return execute_tool_with_permission(tool_name, tool, result), False


def evaluate_sandbox(
    tool_name: str,
    result: ToolResult,
    *,
    sandbox_manager=None,
    arguments: Optional[Dict[str, Any]] = None,
) -> Optional[ToolResult]:
    """Evaluate a tool preview through the sandbox manager."""
    if sandbox_manager is None:
        return None
    try:
        decision = sandbox_manager.evaluate(tool_name, arguments or {}, result)
    except SandboxProtocolError as exc:
        return protocol_error_result(exc)
    except Exception as exc:
        return protocol_error_result(exc)
    return decision_to_tool_result(decision)
