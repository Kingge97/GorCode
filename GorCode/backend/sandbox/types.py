"""
Sandbox protocol types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol

from ..tools.core_tool_support.base import ToolResult


SANDBOX_EFFECTS = {"allow", "deny", "ask", "handled"}


@dataclass(frozen=True)
class SandboxRequest:
    """Immutable request passed to a sandbox provider."""

    tool_name: str
    operation: str
    arguments: Mapping[str, Any]
    metadata: Mapping[str, Any]
    workspace_root: Path
    cwd: Optional[Path] = None
    tool_result_preview: Optional[ToolResult] = None


@dataclass(frozen=True)
class SandboxDecision:
    """Decision returned by a sandbox provider."""

    effect: str
    reason: str
    rule_id: Optional[str] = None
    details: Mapping[str, Any] = field(default_factory=dict)
    result: Optional[ToolResult] = None


class SandboxProvider(Protocol):
    """Provider protocol implemented by builtin or custom sandboxes."""

    def decide(self, request: SandboxRequest) -> SandboxDecision:
        """Return an allow, deny, ask, or handled decision."""
        ...


class SandboxError(RuntimeError):
    """Base error for sandbox configuration and protocol failures."""


class SandboxProtocolError(SandboxError):
    """Raised when a provider violates the sandbox protocol."""


class SandboxUnsupportedToolError(SandboxError):
    """Raised when an enabled sandbox cannot evaluate a tool."""
