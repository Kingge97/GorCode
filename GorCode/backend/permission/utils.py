"""
Permission Utilities
====================

Shared helpers for permission checks across tool execution paths.
"""

from typing import Any, Dict, Optional, Tuple

from . import PermissionManager, PermissionResponse, PermissionType
from .contracts import PermissionRequester, PermissionRequestInput


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
    permission_requester: Optional[PermissionRequester],
    permission_type: PermissionType,
    metadata: Optional[Dict[str, Any]] = None,
    tool_name: Optional[str] = None,
    request_context: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Optional[str], bool]:
    """
    Request permission through the protocol requester.

    Args:
        permission_manager: Session permission manager
        permission_requester: Protocol requester that waits for frontend response
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

    if not permission_requester:
        return False, "Permission denied (no permission requester set)", False

    request = _build_permission_request(tool_name, permission_type, metadata, request_context)
    result = permission_requester.request_permission(request)
    response_str = result.response.value
    reason = result.reason

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


def _build_permission_request(
    tool_name: str,
    permission_type: PermissionType,
    metadata: Optional[Dict[str, Any]],
    request_context: Optional[Dict[str, Any]],
) -> PermissionRequestInput:
    context = request_context or {}
    return PermissionRequestInput(
        request_id=context.get("request_id"),
        tool_call_id=str(context.get("tool_call_id", "") or ""),
        tool_name=tool_name,
        permission_type=permission_type,
        metadata=dict(metadata or {}),
        session_id=context.get("session_id"),
        stream_id=context.get("stream_id"),
        frontend_channel_id=str(context.get("frontend_channel_id", "cli") or "cli"),
        agent_name=context.get("agent_name"),
        agent_run_id=context.get("agent_run_id"),
    )
