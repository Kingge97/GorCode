"""
Built-in rule-only sandbox provider.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .command_classifier import CommandClassification, classify_command
from .path_scope import path_scope, resolve_workspace
from .tool_adapter import is_known_read_tool, target_paths_for
from .types import SandboxDecision, SandboxRequest


class DefaultRulesSandboxProvider:
    """Default rule-only provider that guards workspace mutations."""

    def __init__(self, unknown_mutation: str = "allow", **params: Any) -> None:
        self._unknown_mutation = params.get("unknown_mutation") or unknown_mutation

    def decide(self, request: SandboxRequest) -> SandboxDecision:
        """Return an allow, ask, or deny decision."""
        tool_name = request.tool_name.lower()
        if is_known_read_tool(tool_name):
            return SandboxDecision("allow", "read-only tool", rule_id="default-read-anywhere")
        if tool_name in {"write", "edit"}:
            operation = "write" if tool_name == "write" else "edit"
            return self._decide_paths(request, operation)
        if tool_name == "bash":
            return self._decide_bash(request)
        return self._decide_third_party(request)

    def _decide_paths(self, request: SandboxRequest, operation: str) -> SandboxDecision:
        paths = target_paths_for(request)
        if not paths:
            return _deny("default-missing-target", request, operation, "no target path")
        outside = _outside_paths(paths, request)
        if outside:
            return _deny(
                "default-deny-outside-mutation",
                request,
                operation,
                f"{operation} target is outside workspace",
                outside,
            )
        return SandboxDecision(
            "allow",
            f"{operation} target is inside workspace",
            rule_id="default-mutate-workspace-only",
        )

    def _decide_bash(self, request: SandboxRequest) -> SandboxDecision:
        command = str(request.metadata.get("command") or request.arguments.get("command") or "")
        classified = classify_command(command)
        if classified.category == "read_only":
            return SandboxDecision("allow", classified.reason, rule_id="default-bash-read-only")
        if classified.category == "unknown_mutation":
            return self._unknown_decision(request, classified)
        paths = [target.path for target in classified.targets]
        if not paths:
            return self._unknown_decision(request, classified)
        return self._decide_bash_targets(request, classified)

    def _unknown_decision(
        self,
        request: SandboxRequest,
        classified: CommandClassification,
    ) -> SandboxDecision:
        details = _bash_details(request, classified)
        effect = self._unknown_mutation
        rule_id = "default-unknown-mutation"
        reason = classified.reason or "command mutation target is unknown"
        return SandboxDecision(effect, reason, rule_id=rule_id, details=details)

    def _decide_bash_targets(
        self,
        request: SandboxRequest,
        classified: CommandClassification,
    ) -> SandboxDecision:
        outside = _outside_command_targets(classified, request)
        if outside:
            return _deny(
                "default-deny-outside-mutation",
                request,
                classified.operation,
                "bash mutation target is outside workspace",
                outside,
                _bash_details(request, classified),
            )
        return SandboxDecision(
            "allow",
            "bash mutation target is inside workspace",
            rule_id="default-mutate-workspace-only",
            details=_bash_details(request, classified),
        )

    def _decide_third_party(self, request: SandboxRequest) -> SandboxDecision:
        if request.operation in {"read", "list", "search"}:
            return SandboxDecision("allow", "declared read-only operation", rule_id="declared-read")
        if request.operation in {"write", "edit", "create", "delete", "move", "copy"}:
            return self._decide_paths(request, request.operation)
        return SandboxDecision(
            "allow",
            "tool lacks sandbox metadata; allowed for permission system",
            rule_id="default-third-party-no-metadata",
        )


def _outside_paths(paths: list[str], request: SandboxRequest) -> list[str]:
    outside = []
    workspace = resolve_workspace(request.workspace_root)
    for path in paths:
        if path_scope(path, workspace, request.cwd) == "outside_workspace":
            outside.append(path)
    return outside


def _outside_command_targets(
    classified: CommandClassification,
    request: SandboxRequest,
) -> list[str]:
    guarded = []
    for target in classified.targets:
        if classified.operation == "copy" and target.role == "source":
            continue
        guarded.append(target.path)
    return _outside_paths(guarded, request)


def _deny(
    rule_id: str,
    request: SandboxRequest,
    operation: str,
    reason: str,
    targets: Optional[list[str]] = None,
    extra: Optional[dict[str, Any]] = None,
) -> SandboxDecision:
    details = {
        "tool": request.tool_name,
        "operation": operation,
        "workspace": str(Path(request.workspace_root).resolve()),
    }
    if targets:
        details["targets"] = targets
    if extra:
        details.update(extra)
    return SandboxDecision("deny", reason, rule_id=rule_id, details=details)


def _bash_details(
    request: SandboxRequest,
    classified: CommandClassification,
) -> dict[str, Any]:
    command = str(request.metadata.get("command") or request.arguments.get("command") or "")
    return {
        "command": command,
        "category": classified.category,
        "operation": classified.operation,
        "targets": [target.path for target in classified.targets],
    }
