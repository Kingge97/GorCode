"""Convenience runtime API used by GorCode backend paths."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from GorCode.backend.tools.core_tool_support.base import ToolResult

from .config import HookSettings, parse_hook_settings
from .events import (
    CHAT_AFTER_MODEL_RESPONSE,
    CHAT_BEFORE_MODEL_REQUEST,
    INPUT_BEFORE_ACCEPT,
    TOOL_AFTER_EXECUTE,
    TOOL_BEFORE_EXECUTE,
)
from .loader import load_hooks
from .manager import HookCallBase, HookEventResult, HookManager
from .result import tool_result_to_dict
from .status import build_hook_status


@dataclass(frozen=True)
class ToolBeforeHookResult:
    arguments: dict[str, Any]
    action: str = "continue"
    reason: Optional[str] = None
    tool_result: Optional[ToolResult] = None
    handled_by_hook: bool = False
    diagnostics: tuple[dict[str, Any], ...] = ()


class HookRuntime:
    def __init__(self, settings: HookSettings, workspace_root: str):
        self.settings = settings
        self.workspace_root = workspace_root
        loaded = load_hooks(settings.hooks) if settings.enabled else ()
        self.manager = HookManager(loaded, enabled=settings.enabled)
        self.loaded_ids = {hook.id for hook in loaded}

    @classmethod
    def from_raw_settings(cls, raw: Mapping[str, Any] | None, workspace_root: str) -> "HookRuntime":
        return cls(parse_hook_settings(raw), workspace_root)

    def new_run_id(self) -> str:
        return f"run-{uuid.uuid4().hex}"

    def before_input_accept(self, text: str, base: HookCallBase, input_kind: str) -> HookEventResult:
        return self.manager.run_event(
            INPUT_BEFORE_ACCEPT,
            {"input": text, "input_kind": input_kind},
            base,
            system_metadata={"stage": "input.before_accept"},
        )

    def before_model_request(
        self,
        messages_with_system: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        base: HookCallBase,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], HookEventResult]:
        system, conversation = _split_system(messages_with_system)
        payload = {
            "messages": copy.deepcopy(conversation),
            "tools": copy.deepcopy(tools),
            "model": {"name": base.model_name},
            "agent": {"name": base.agent_name},
            "system_prompt": {"available": False, "length": len(system.get("content", ""))},
        }
        result = self.manager.run_event(
            CHAT_BEFORE_MODEL_REQUEST,
            payload,
            base,
            system_metadata={"stage": "chat.before_model_request"},
        )
        return [system] + result.payload["messages"], result.payload["tools"], result

    def after_model_response(self, payload: Mapping[str, Any], base: HookCallBase) -> HookEventResult:
        return self.manager.run_event(
            CHAT_AFTER_MODEL_RESPONSE,
            payload,
            base,
            system_metadata={"stage": "chat.after_model_response"},
        )

    def before_tool_execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        tool_call_id: str,
        base: HookCallBase,
    ) -> ToolBeforeHookResult:
        payload = {
            "tool_name": tool_name,
            "arguments": copy.deepcopy(dict(arguments)),
            "tool_call_id": tool_call_id,
            "source": base.source,
        }
        result = self.manager.run_event(
            TOOL_BEFORE_EXECUTE,
            payload,
            base,
            system_metadata={"stage": "tool.before_execute"},
        )
        return ToolBeforeHookResult(
            arguments=result.payload["arguments"],
            action=result.action,
            reason=result.reason,
            tool_result=result.tool_result,
            handled_by_hook=result.handled_by_hook,
            diagnostics=tuple(result.diagnostics),
        )

    def after_tool_execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        result: ToolResult,
        base: HookCallBase,
        *,
        handled_by_hook: bool = False,
        handled_by_sandbox: bool = False,
    ) -> ToolResult:
        payload = _tool_after_payload(tool_name, arguments, result, handled_by_hook, handled_by_sandbox)
        event_result = self.manager.run_event(
            TOOL_AFTER_EXECUTE,
            payload,
            base,
            system_metadata={"stage": "tool.after_execute"},
            original_tool_result=result,
        )
        changed = event_result.payload.get("result")
        return changed if isinstance(changed, ToolResult) else result

    def notify_error(self, error: Exception, base: HookCallBase, stage: str) -> HookEventResult:
        return self.manager.run_on_error(error, base, stage=stage)

    def status(self) -> dict[str, Any]:
        return build_hook_status(self.settings, self.loaded_ids)


def make_call_base(
    *,
    runtime: HookRuntime,
    run_id: str,
    session_id: Optional[str],
    source: str,
    agent_name: str,
    model_name: Optional[str],
    agent_run_id: Optional[str] = None,
    parent_agent: Optional[str] = None,
    subagent_type: Optional[str] = None,
) -> HookCallBase:
    return HookCallBase(
        run_id=run_id,
        session_id=session_id,
        source=source,
        agent_name=agent_name,
        agent_run_id=agent_run_id,
        parent_agent=parent_agent,
        subagent_type=subagent_type,
        model_name=model_name,
        workspace_root=runtime.workspace_root,
    )


def _split_system(messages: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if messages and messages[0].get("role") == "system":
        return copy.deepcopy(messages[0]), copy.deepcopy(messages[1:])
    return {"role": "system", "content": ""}, copy.deepcopy(messages)


def _tool_after_payload(
    tool_name: str,
    arguments: Mapping[str, Any],
    result: ToolResult,
    handled_by_hook: bool,
    handled_by_sandbox: bool,
) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "arguments": copy.deepcopy(dict(arguments)),
        "result": tool_result_to_dict(result),
        "handled_by_hook": handled_by_hook,
        "handled_by_sandbox": handled_by_sandbox,
    }
