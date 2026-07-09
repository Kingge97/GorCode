"""
Permission Manager
==================

Session-level permission management for dangerous operations.
"""

from enum import Enum
from typing import Any, Callable, Dict, Optional
from dataclasses import dataclass, field

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

        # Permission rules/settings
        self._settings = PermissionSettings.from_config(None)
        self._rule_engine = PermissionRuleEngine(self._settings)
        self._deny_tracker: Dict[str, int] = {}
        self._hooks: list[Callable[[PermissionDecision, Dict[str, Any]], None]] = []

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
