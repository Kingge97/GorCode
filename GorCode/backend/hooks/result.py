"""HookResult parsing and validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Optional

from GorCode.backend.tools.core_tool_support.base import ToolResult

from .errors import HookExecutionError
from .events import (
    CHAT_BEFORE_MODEL_REQUEST,
    EVENT_ALLOWED_ACTIONS,
    EVENT_ALLOWED_FIELDS,
    TOOL_AFTER_EXECUTE,
    TOOL_BEFORE_EXECUTE,
)


@dataclass(frozen=True)
class HookResult:
    """Unified result envelope returned by GorCode hooks."""

    action: str = "continue"
    input: Optional[str] = None
    messages: Optional[list[dict[str, Any]]] = None
    tools: Optional[list[dict[str, Any]]] = None
    arguments: Optional[dict[str, Any]] = None
    tool_result: Optional[ToolResult | dict[str, Any]] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    reason: Optional[str] = None


def parse_hook_result(value: Any) -> HookResult:
    if value is None:
        return HookResult()
    if isinstance(value, HookResult):
        return value
    if isinstance(value, Mapping):
        data = dict(value)
        allowed = set(HookResult.__dataclass_fields__.keys())
        extra = set(data.keys()) - allowed
        if extra:
            raise HookExecutionError(f"Unknown HookResult field(s): {sorted(extra)}")
        return HookResult(**data)
    raise HookExecutionError("Hook handler must return HookResult, dict, or None")


def validate_hook_result(
    event: str,
    result: HookResult,
    context_metadata: Mapping[str, Any],
    original_tool_result: Optional[ToolResult] = None,
) -> HookResult:
    _validate_action(event, result.action)
    _validate_allowed_fields(event, result)
    _validate_common(result, context_metadata)
    converted = _convert_tool_result(result)
    _validate_event_specific(event, converted, original_tool_result)
    return converted


def tool_result_to_dict(result: ToolResult) -> dict[str, Any]:
    return {
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "metadata": dict(result.metadata or {}),
    }


def tool_result_from_value(value: Any) -> ToolResult:
    if isinstance(value, ToolResult):
        return value
    if not isinstance(value, Mapping):
        raise HookExecutionError("tool_result must be ToolResult or dict")
    data = dict(value)
    if not isinstance(data.get("success"), bool):
        raise HookExecutionError("tool_result.success must be bool")
    if not isinstance(data.get("output"), str):
        raise HookExecutionError("tool_result.output must be str")
    error = data.get("error")
    if error is not None and not isinstance(error, str):
        raise HookExecutionError("tool_result.error must be str or None")
    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise HookExecutionError("tool_result.metadata must be dict")
    return ToolResult(data["success"], data["output"], error, metadata)


def _validate_action(event: str, action: str) -> None:
    if action not in EVENT_ALLOWED_ACTIONS.get(event, ()):
        raise HookExecutionError(f"Action '{action}' is not allowed for event '{event}'")


def _validate_allowed_fields(event: str, result: HookResult) -> None:
    allowed = set(EVENT_ALLOWED_FIELDS[event])
    for name in ("input", "messages", "tools", "arguments", "tool_result", "reason"):
        if getattr(result, name) is not None and name not in allowed:
            raise HookExecutionError(f"Field '{name}' is not allowed for event '{event}'")


def _validate_common(result: HookResult, context_metadata: Mapping[str, Any]) -> None:
    if not isinstance(result.metadata, Mapping):
        raise HookExecutionError("HookResult.metadata must be a mapping")
    if not isinstance(result.diagnostics, list):
        raise HookExecutionError("HookResult.diagnostics must be list[dict]")
    if not all(isinstance(item, dict) for item in result.diagnostics):
        raise HookExecutionError("HookResult.diagnostics must be list[dict]")
    if result.reason is not None and not isinstance(result.reason, str):
        raise HookExecutionError("HookResult.reason must be str or None")
    _validate_metadata(result.metadata, context_metadata)


def _convert_tool_result(result: HookResult) -> HookResult:
    if result.tool_result is None:
        return result
    tool_result = tool_result_from_value(result.tool_result)
    return HookResult(
        action=result.action,
        input=result.input,
        messages=result.messages,
        tools=result.tools,
        arguments=result.arguments,
        tool_result=tool_result,
        metadata=result.metadata,
        diagnostics=result.diagnostics,
        reason=result.reason,
    )


def _validate_event_specific(
    event: str,
    result: HookResult,
    original_tool_result: Optional[ToolResult],
) -> None:
    if result.input is not None and not isinstance(result.input, str):
        raise HookExecutionError("HookResult.input must be str")
    if result.messages is not None:
        _validate_messages(event, result.messages)
    if result.tools is not None:
        _validate_tools(result.tools)
    if result.arguments is not None and not isinstance(result.arguments, dict):
        raise HookExecutionError("HookResult.arguments must be dict")
    if result.action == "deny" and not result.reason:
        raise HookExecutionError("deny action requires reason")
    if result.reason and result.action != "deny":
        raise HookExecutionError("reason is only allowed with deny")
    if result.action == "handled" and result.tool_result is None:
        raise HookExecutionError("handled action requires tool_result")
    if event == TOOL_BEFORE_EXECUTE and result.tool_result is not None:
        if result.action != "handled":
            raise HookExecutionError("tool_result is only allowed with handled")
    _validate_after_tool(event, result, original_tool_result)


def _validate_messages(event: str, messages: Any) -> None:
    if not isinstance(messages, list) or not all(isinstance(item, dict) for item in messages):
        raise HookExecutionError("HookResult.messages must be list[dict]")
    for message in messages:
        role = message.get("role")
        if role not in {"user", "assistant", "tool"}:
            raise HookExecutionError(f"Unsupported message role: {role}")
        if event == CHAT_BEFORE_MODEL_REQUEST and role == "system":
            raise HookExecutionError("chat.before_model_request cannot return system messages")
        if role == "tool" and not message.get("tool_call_id"):
            raise HookExecutionError("tool role messages require tool_call_id")
        if "tool_calls" in message and not isinstance(message["tool_calls"], list):
            raise HookExecutionError("assistant.tool_calls must be list")


def _validate_tools(tools: Any) -> None:
    if not isinstance(tools, list) or not all(isinstance(tool, dict) for tool in tools):
        raise HookExecutionError("HookResult.tools must be list[dict]")
    for tool in tools:
        if not all(key in tool for key in ("name", "description", "parameters")):
            raise HookExecutionError("Each tool must include name, description, parameters")
        if not isinstance(tool.get("parameters"), dict):
            raise HookExecutionError("tool.parameters must be dict")


def _validate_metadata(metadata: Mapping[str, Any], context_metadata: Mapping[str, Any]) -> None:
    for key in metadata.keys():
        if not isinstance(key, str) or not key:
            raise HookExecutionError("metadata top-level keys must be non-empty str")
        if key == "gorcode":
            raise HookExecutionError("metadata namespace 'gorcode' is reserved")
        if key in context_metadata:
            raise HookExecutionError(f"metadata namespace already exists: {key}")


def _validate_after_tool(
    event: str,
    result: HookResult,
    original_tool_result: Optional[ToolResult],
) -> None:
    if event != TOOL_AFTER_EXECUTE or result.tool_result is None or original_tool_result is None:
        return
    new_result = result.tool_result
    if not original_tool_result.success and new_result.success:
        raise HookExecutionError("tool.after_execute cannot convert failure to success")
