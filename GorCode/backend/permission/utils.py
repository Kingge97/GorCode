"""
Permission Utilities
====================

Shared helpers for permission checks across tool execution paths.
"""

from typing import Any, Dict, Optional, Tuple

from . import PermissionManager, PermissionResponse, PermissionType


def get_permission_type(tool_name: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[PermissionType]:
    """
    Map tool name and metadata to a PermissionType.

    Args:
        tool_name: Tool name (write/edit/bash)
        metadata: Tool metadata (used for bash delete detection)

    Returns:
        PermissionType or None if no permission is required
    """
    if tool_name == "write":
        return PermissionType.WRITE
    if tool_name == "edit":
        return PermissionType.EDIT
    if tool_name == "bash":
        has_delete = (metadata or {}).get("has_delete")
        return PermissionType.BASH_DELETE if has_delete else PermissionType.BASH
    return None


def request_permission_sync(
    permission_manager: Optional[PermissionManager],
    permission_callback,
    permission_type: PermissionType,
    metadata: Optional[Dict[str, Any]] = None,
    tool_name: Optional[str] = None,
) -> Tuple[bool, Optional[str], bool]:
    """
    Request permission using the sync callback flow.

    Args:
        permission_manager: Session permission manager
        permission_callback: UI callback (sync) returning response or (response, reason)
        permission_type: Permission type to request
        metadata: Metadata for the permission prompt

    Returns:
        (granted, error_message, rejected_without_reason)
    """
    if not permission_manager:
        return True, None, False

    tool_name = tool_name or permission_type.value
    decision = permission_manager.decide(tool_name, permission_type, metadata)
    if decision.decision == "allow":
        return True, None, False
    if decision.decision == "deny":
        return False, decision.reason or "Permission denied", False

    if not permission_callback:
        return False, "Permission denied (no callback set)", False

    callback_result = permission_callback(permission_type.value, metadata or {})
    if isinstance(callback_result, tuple):
        response, reason = callback_result
    else:
        response, reason = callback_result, None

    if isinstance(response, PermissionResponse):
        response = response.value

    response_str = str(response).lower() if response is not None else ""

    if response_str == "always":
        permission_manager.grant_session_permission(permission_type)
        return True, None, False
    if response_str == "once":
        return True, None, False

    if reason and str(reason).strip():
        permission_manager.record_denial(tool_name, metadata)
        return False, f"操作被用户拒绝 - {reason}", False

    permission_manager.record_denial(tool_name, metadata)
    return False, "用户拒绝操作且未提供理由", True
