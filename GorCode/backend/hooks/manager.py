"""HookManager for sorted execution, scope checks, and metadata flow."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from GorCode.backend.tools.core_tool_support.base import ToolResult

from .config import HookScope
from .context import HookContext
from .errors import HookExecutionError
from .events import RUN_ON_ERROR
from .loader import LoadedHook
from .result import HookResult, parse_hook_result, validate_hook_result


@dataclass(frozen=True)
class HookEventResult:
    action: str = "continue"
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    reason: Optional[str] = None
    tool_result: Optional[ToolResult] = None
    handled_by_hook: bool = False


@dataclass(frozen=True)
class HookCallBase:
    run_id: str
    session_id: Optional[str]
    source: str
    agent_name: str
    agent_run_id: Optional[str]
    parent_agent: Optional[str]
    subagent_type: Optional[str]
    model_name: Optional[str]
    workspace_root: str


class HookManager:
    def __init__(self, hooks: tuple[LoadedHook, ...] = (), enabled: bool = True):
        self.enabled = enabled
        self._hooks = tuple(sorted(hooks, key=_sort_key))
        self._metadata_by_run: dict[str, dict[str, Any]] = {}

    @property
    def hooks(self) -> tuple[LoadedHook, ...]:
        return self._hooks

    def run_event(
        self,
        event: str,
        payload: Mapping[str, Any],
        base: HookCallBase,
        *,
        system_metadata: Optional[Mapping[str, Any]] = None,
        original_tool_result: Optional[ToolResult] = None,
    ) -> HookEventResult:
        current_payload = copy.deepcopy(dict(payload))
        diagnostics: list[dict[str, Any]] = []
        if not self.enabled:
            return HookEventResult(payload=current_payload)
        for hook in self._matching_hooks(event, current_payload, base):
            context = self._make_context(event, current_payload, base, system_metadata)
            result = self._invoke(hook, context)
            validated = validate_hook_result(
                event,
                result,
                self._run_metadata(base.run_id),
                original_tool_result,
            )
            diagnostics.extend(validated.diagnostics)
            self._merge_metadata(base.run_id, validated.metadata)
            current_payload = _apply_payload_changes(event, current_payload, validated)
            if validated.action in {"deny", "handled"}:
                return _short_result(
                    validated,
                    current_payload,
                    diagnostics,
                    self._run_metadata(base.run_id),
                )
        return HookEventResult(
            payload=current_payload,
            metadata=dict(self._run_metadata(base.run_id)),
            diagnostics=diagnostics,
        )

    def run_on_error(
        self,
        error: Exception,
        base: HookCallBase,
        *,
        stage: str,
        event: Optional[str] = None,
        hook_id: Optional[str] = None,
    ) -> HookEventResult:
        payload = _error_payload(error, stage, event, hook_id)
        try:
            return self.run_event(RUN_ON_ERROR, payload, base, system_metadata={"stage": stage})
        except Exception as secondary:
            diagnostics = [{
                "level": "error",
                "message": str(secondary),
                "secondary": True,
            }]
            return HookEventResult(payload=payload, diagnostics=diagnostics)

    def _matching_hooks(
        self,
        event: str,
        payload: Mapping[str, Any],
        base: HookCallBase,
    ) -> list[LoadedHook]:
        tool_name = payload.get("tool_name")
        return [
            hook for hook in self._hooks
            if hook.config.event == event
            and _scope_matches(hook.config.scope, base, tool_name)
        ]

    def _make_context(
        self,
        event: str,
        payload: Mapping[str, Any],
        base: HookCallBase,
        system_metadata: Optional[Mapping[str, Any]],
    ) -> HookContext:
        return HookContext(
            event=event,
            run_id=base.run_id,
            hook_run_id=f"hookrun-{uuid.uuid4().hex}",
            session_id=base.session_id,
            source=base.source,
            agent_name=base.agent_name,
            agent_run_id=base.agent_run_id,
            parent_agent=base.parent_agent,
            subagent_type=base.subagent_type,
            model_name=base.model_name,
            workspace_root=base.workspace_root,
            payload=payload,
            system_metadata=system_metadata or {},
            metadata=self._run_metadata(base.run_id),
        )

    def _invoke(self, hook: LoadedHook, context: HookContext) -> HookResult:
        try:
            handler = hook.handler
            raw = handler.handle(context) if hasattr(handler, "handle") else handler(context)
            return parse_hook_result(raw)
        except HookExecutionError:
            raise
        except Exception as exc:
            message = f"Hook '{hook.id}' failed during '{context.event}': {exc}"
            raise HookExecutionError(message) from exc

    def _merge_metadata(self, run_id: str, metadata: Mapping[str, Any]) -> None:
        if not metadata:
            return
        run_metadata = self._metadata_by_run.setdefault(run_id, {})
        for key, value in metadata.items():
            run_metadata[key] = copy.deepcopy(value)

    def _run_metadata(self, run_id: str) -> dict[str, Any]:
        return self._metadata_by_run.setdefault(run_id, {})


def _sort_key(hook: LoadedHook) -> tuple[int, int]:
    return (-hook.config.priority, hook.config.order)


def _scope_matches(scope: HookScope, base: HookCallBase, tool_name: Any) -> bool:
    return scope.matches(
        source=base.source,
        agent_name=base.agent_name,
        subagent_type=base.subagent_type,
        tool_name=str(tool_name) if tool_name is not None else None,
    )


def _apply_payload_changes(
    event: str,
    payload: dict[str, Any],
    result: HookResult,
) -> dict[str, Any]:
    changed = copy.deepcopy(payload)
    for field_name in ("input", "messages", "tools", "arguments"):
        value = getattr(result, field_name)
        if value is not None:
            changed[field_name] = copy.deepcopy(value)
    if result.tool_result is not None:
        changed["result"] = result.tool_result
    return changed


def _short_result(
    result: HookResult,
    payload: dict[str, Any],
    diagnostics: list[dict[str, Any]],
    metadata: Mapping[str, Any],
) -> HookEventResult:
    return HookEventResult(
        action=result.action,
        payload=payload,
        metadata=dict(metadata),
        diagnostics=diagnostics,
        reason=result.reason,
        tool_result=result.tool_result if isinstance(result.tool_result, ToolResult) else None,
        handled_by_hook=result.action == "handled",
    )


def _error_payload(
    error: Exception,
    stage: str,
    event: Optional[str],
    hook_id: Optional[str],
) -> dict[str, Any]:
    return {
        "error_type": error.__class__.__name__,
        "message": str(error),
        "stage": stage,
        "event": event,
        "hook_id": hook_id,
        "diagnostics": [],
    }
