"""
Permission Manager
==================

Session-level permission management for dangerous operations.
"""

from enum import Enum
from typing import Any, Callable, Dict, Optional, Set
from dataclasses import dataclass, field
import asyncio

from .rules import (
    PermissionDecision,
    PermissionMode,
    PermissionRuleEngine,
    PermissionSettings,
)


class PermissionType(Enum):
    """Types of operations that require permission."""
    WRITE = "write"           # File write/creation
    EDIT = "edit"             # File editing
    BASH = "bash"             # Bash command execution
    BASH_DELETE = "bash_delete"  # Bash commands with delete operations


class PermissionResponse(Enum):
    """User responses to permission requests."""
    ONCE = "once"             # Allow once
    ALWAYS = "always"         # Allow for entire session
    REJECT = "reject"         # Reject the operation


@dataclass
class PermissionRequest:
    """A permission request waiting for user response."""

    request_id: str
    permission_type: PermissionType
    metadata: Dict = field(default_factory=dict)

    # For async waiting
    future: Optional[asyncio.Future] = None


class PermissionManager:
    """
    Manages session-level permissions for dangerous operations.

    Features:
    - Request user permission for dangerous operations
    - Remember user choices for the session
    - Provide UI callbacks for permission dialogs
    """

    def __init__(self):
        """Initialize permission manager."""
        # Session-level permissions: {PermissionType: bool}
        self._session_permissions: Dict[PermissionType, bool] = {}

        # Pending requests: {request_id: PermissionRequest}
        self._pending_requests: Dict[str, PermissionRequest] = {}

        # Request counter for generating IDs
        self._request_counter = 0

        # Permission request callback (set by UI)
        self._permission_callback = None

        # Permission rules/settings
        self._settings = PermissionSettings.from_config(None)
        self._rule_engine = PermissionRuleEngine(self._settings)
        self._deny_tracker: Dict[str, int] = {}
        self._hooks: list[Callable[[PermissionDecision, Dict[str, Any]], None]] = []

    def set_permission_callback(self, callback):
        """
        Set callback for permission requests.

        Args:
            callback: Async function(request_id, permission_type, metadata) -> PermissionResponse
        """
        self._permission_callback = callback

    def apply_settings(self, config: Any) -> None:
        """Apply permission settings from config."""
        self._settings = PermissionSettings.from_config(config)
        self._rule_engine = PermissionRuleEngine(self._settings)
        self._deny_tracker.clear()

    def register_hook(self, hook: Callable[[PermissionDecision, Dict[str, Any]], None]) -> None:
        """Register a hook for permission decisions."""
        self._hooks.append(hook)

    def decide(
        self,
        tool_name: str,
        permission_type: PermissionType,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PermissionDecision:
        return self._evaluate_decision(tool_name, permission_type, metadata, emit_hooks=True)

    def should_prompt(
        self,
        tool_name: str,
        permission_type: PermissionType,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        decision = self._evaluate_decision(tool_name, permission_type, metadata, emit_hooks=False)
        return decision.decision == "ask"

    def record_denial(self, tool_name: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        key = _build_denial_key(tool_name, metadata or {})
        self._deny_tracker[key] = self._deny_tracker.get(key, 0) + 1

    def grant_session_permission(self, permission_type: PermissionType) -> None:
        """
        Grant permission for the entire session.

        Args:
            permission_type: Type of permission to grant
        """
        self._session_permissions[permission_type] = True

    def revoke_session_permission(self, permission_type: PermissionType) -> None:
        """
        Revoke session permission.

        Args:
            permission_type: Type of permission to revoke
        """
        if permission_type in self._session_permissions:
            del self._session_permissions[permission_type]

    def has_session_permission(self, permission_type: PermissionType) -> bool:
        """
        Check if permission is granted for the session.

        Args:
            permission_type: Type of permission to check

        Returns:
            True if permission is granted
        """
        return self._session_permissions.get(permission_type, False)

    def get_session_permissions(self) -> Dict[PermissionType, bool]:
        """
        Get all session permissions.

        Returns:
            Dictionary of permission types and their status
        """
        return self._session_permissions.copy()

    def clear_session_permissions(self) -> None:
        """Clear all session permissions."""
        self._session_permissions.clear()

    async def request_permission(
        self,
        tool_name: str,
        permission_type: PermissionType,
        metadata: Dict = None,
    ) -> PermissionResponse:
        """
        Request permission from user.

        Args:
            permission_type: Type of permission needed
            metadata: Additional context for the request (file_path, command, diff, etc.)

        Returns:
            PermissionResponse from user

        Raises:
            RuntimeError: If no permission callback is set
        """
        decision = self.decide(tool_name, permission_type, metadata)
        if decision.decision == "allow":
            return PermissionResponse.ONCE
        if decision.decision == "deny":
            return PermissionResponse.REJECT

        # No callback set - default to reject for safety
        if self._permission_callback is None:
            return PermissionResponse.REJECT

        # Generate request ID
        self._request_counter += 1
        request_id = f"perm_{self._request_counter}"

        # Create request
        future = asyncio.Future()
        request = PermissionRequest(
            request_id=request_id,
            permission_type=permission_type,
            metadata=metadata or {},
            future=future,
        )
        self._pending_requests[request_id] = request

        # Call UI callback
        try:
            response = await self._permission_callback(
                request_id,
                permission_type,
                metadata or {},
            )

            # Handle response
            if response == PermissionResponse.ALWAYS:
                self.grant_session_permission(permission_type)
            if response == PermissionResponse.REJECT:
                self.record_denial(tool_name, metadata)

            return response

        finally:
            # Clean up
            if request_id in self._pending_requests:
                del self._pending_requests[request_id]

    def respond_to_request(self, request_id: str, response: PermissionResponse) -> bool:
        """
        Respond to a pending permission request.

        Args:
            request_id: ID of the request
            response: User's response

        Returns:
            True if request was found and handled
        """
        if request_id not in self._pending_requests:
            return False

        request = self._pending_requests[request_id]

        # Handle ALWAYS response
        if response == PermissionResponse.ALWAYS:
            self.grant_session_permission(request.permission_type)

        # Set future result
        if request.future and not request.future.done():
            request.future.set_result(response)

        # Clean up
        del self._pending_requests[request_id]
        return True

    def get_pending_requests(self) -> Dict[str, PermissionRequest]:
        """
        Get all pending permission requests.

        Returns:
            Dictionary of request IDs to PermissionRequest objects
        """
        return self._pending_requests.copy()

    def _apply_mode(
        self,
        tool_name: str,
        permission_type: PermissionType,
    ) -> Optional[PermissionDecision]:
        mode = self._settings.mode
        if mode == PermissionMode.BYPASS:
            return PermissionDecision("allow", reason="bypass")
        if mode == PermissionMode.ACCEPT_EDITS and tool_name in ("write", "edit"):
            return PermissionDecision("allow", reason="acceptEdits")
        if mode == PermissionMode.DONT_ASK:
            return PermissionDecision("deny", reason="dontAsk")
        return None

    def _emit_hooks(self, decision: PermissionDecision, metadata: Dict[str, Any]) -> None:
        for hook in list(self._hooks):
            hook(decision, metadata)

    def _is_denied_too_often(self, tool_name: str, metadata: Dict[str, Any]) -> bool:
        if self._settings.deny_limit <= 0:
            return False
        key = _build_denial_key(tool_name, metadata)
        return self._deny_tracker.get(key, 0) >= self._settings.deny_limit

    def _evaluate_decision(
        self,
        tool_name: str,
        permission_type: PermissionType,
        metadata: Optional[Dict[str, Any]],
        *,
        emit_hooks: bool,
    ) -> PermissionDecision:
        payload = metadata or {}
        if self.has_session_permission(permission_type):
            decision = PermissionDecision("allow", reason="session")
            if emit_hooks:
                self._emit_hooks(decision, payload)
            return decision
        mode_decision = self._apply_mode(tool_name, permission_type)
        if mode_decision:
            if emit_hooks:
                self._emit_hooks(mode_decision, payload)
            return mode_decision
        rule_decision = self._rule_engine.evaluate(tool_name, payload)
        if rule_decision:
            if emit_hooks:
                self._emit_hooks(rule_decision, payload)
            return rule_decision
        classifier_decision = self._rule_engine.classify(tool_name, payload)
        if classifier_decision:
            if emit_hooks:
                self._emit_hooks(classifier_decision, payload)
            return classifier_decision
        if self._is_denied_too_often(tool_name, payload):
            decision = PermissionDecision("deny", reason="deny_limit")
            if emit_hooks:
                self._emit_hooks(decision, payload)
            return decision
        decision = PermissionDecision("ask", reason="default")
        if emit_hooks:
            self._emit_hooks(decision, payload)
        return decision


def _build_denial_key(tool_name: str, metadata: Dict[str, Any]) -> str:
    file_path = metadata.get("file_path") or metadata.get("path") or ""
    command = metadata.get("command") or ""
    return f"{tool_name}:{file_path}:{command}"


# Global permission manager instance
_permission_manager = PermissionManager()


def get_permission_manager() -> PermissionManager:
    """Get the global permission manager instance."""
    return _permission_manager
