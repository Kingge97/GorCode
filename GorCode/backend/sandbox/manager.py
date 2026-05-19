"""
Sandbox manager and execution helpers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ..tools.core_tool_support.base import ToolResult
from .config import SandboxSettings
from .provider import load_provider
from .tool_adapter import build_request
from .types import SANDBOX_EFFECTS, SandboxDecision, SandboxProtocolError


class SandboxManager:
    """Evaluate tool previews through the configured sandbox provider."""

    def __init__(self, settings: SandboxSettings, workspace_root: Path, provider=None) -> None:
        self._settings = settings
        self._workspace_root = Path(workspace_root).resolve()
        self._provider = provider or load_provider(settings)

    @classmethod
    def from_config(cls, config: Any, workspace_root: Path) -> "SandboxManager":
        """Create a sandbox manager from GorCode config."""
        settings = SandboxSettings.from_config(config, base_path=workspace_root)
        return cls(settings=settings, workspace_root=workspace_root)

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    def set_enabled(self, enabled: bool) -> None:
        """Set session-level sandbox enablement."""
        self._settings = self._settings.with_enabled(enabled)

    def reload(self, config: Any) -> None:
        """Reload settings and provider from config."""
        self._settings = SandboxSettings.from_config(config, base_path=self._workspace_root)
        self._provider = load_provider(self._settings)

    def status(self) -> Dict[str, Any]:
        """Return a serializable status payload."""
        provider = dict(self._settings.provider)
        params = dict(provider.get("params") or {})
        return {
            "enabled": self._settings.enabled,
            "provider": {
                "type": provider.get("type", "builtin"),
                "name": provider.get("name"),
                "module": provider.get("module"),
                "factory": provider.get("factory"),
                "command": provider.get("command"),
                "url": provider.get("url"),
                "handled_tools": provider.get("handled_tools") or params.get("handled_tools"),
                "proxy_all_tools": bool(provider.get("proxy_all_tools") or params.get("proxy_all_tools")),
            },
            "config_path": self._settings.config_path,
            "unknown_mutation": self._settings.unknown_mutation,
            "workspace_root": str(self._workspace_root),
        }

    def requires_pre_execution(self, tool_name: str) -> bool:
        """Return true when provider declares it may handle this tool before host execution."""
        if not self._settings.enabled:
            return False
        provider = dict(self._settings.provider)
        params = dict(provider.get("params") or {})
        if bool(provider.get("proxy_all_tools") or params.get("proxy_all_tools")):
            return True
        handled = provider.get("handled_tools") or params.get("handled_tools") or []
        handled_tools = {str(item).lower() for item in handled}
        return tool_name.lower() in handled_tools

    def evaluate_pre_execution(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Optional[ToolResult]:
        """Evaluate a declared execution/proxy provider before host tool execution."""
        if not self.requires_pre_execution(tool_name):
            return None
        preview = ToolResult(success=True, output="", metadata={})
        decision = self.evaluate(tool_name, arguments, preview)
        return decision_to_tool_result(decision)

    def evaluate(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        preview_result: ToolResult,
    ) -> SandboxDecision:
        """Evaluate a tool preview and validate the provider response."""
        if not self._settings.enabled:
            return SandboxDecision("allow", "sandbox_disabled")
        request = build_request(tool_name, arguments, preview_result, self._workspace_root)
        decision = self._provider.decide(request)
        return self._validate_decision(decision)

    def _validate_decision(self, decision: SandboxDecision) -> SandboxDecision:
        if decision.effect not in SANDBOX_EFFECTS:
            raise SandboxProtocolError(f"Invalid sandbox effect: {decision.effect}")
        if decision.effect == "handled" and decision.result is None:
            raise SandboxProtocolError("Sandbox returned handled without ToolResult")
        return decision


def decision_to_tool_result(decision: SandboxDecision) -> Optional[ToolResult]:
    """Convert deny/handled decisions into tool results."""
    if decision.effect == "handled":
        return decision.result
    if decision.effect != "deny":
        return None
    return ToolResult(
        success=False,
        output="",
        error=_format_denial(decision),
        metadata={"sandbox": dict(decision.details), "rule_id": decision.rule_id},
    )


def protocol_error_result(error: Exception) -> ToolResult:
    """Expose sandbox protocol failures as explicit tool failures."""
    return ToolResult(success=False, output="", error=f"Sandbox error: {error}")


def _format_denial(decision: SandboxDecision) -> str:
    lines = ["Sandbox denied operation"]
    if decision.rule_id:
        lines.append(f"rule: {decision.rule_id}")
    for key, value in dict(decision.details).items():
        lines.append(f"{key}: {value}")
    if decision.reason:
        lines.append(f"reason: {decision.reason}")
    return "\n".join(lines)
