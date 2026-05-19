"""Hook event names and capability schema."""

from __future__ import annotations

INPUT_BEFORE_ACCEPT = "gorcode.hook.input.before_accept"
CHAT_BEFORE_MODEL_REQUEST = "gorcode.hook.chat.before_model_request"
CHAT_AFTER_MODEL_RESPONSE = "gorcode.hook.chat.after_model_response"
TOOL_BEFORE_EXECUTE = "gorcode.hook.tool.before_execute"
TOOL_AFTER_EXECUTE = "gorcode.hook.tool.after_execute"
RUN_ON_ERROR = "gorcode.hook.run.on_error"

ALL_HOOK_EVENTS = (
    INPUT_BEFORE_ACCEPT,
    CHAT_BEFORE_MODEL_REQUEST,
    CHAT_AFTER_MODEL_RESPONSE,
    TOOL_BEFORE_EXECUTE,
    TOOL_AFTER_EXECUTE,
    RUN_ON_ERROR,
)

EVENT_CAPABILITIES = {
    INPUT_BEFORE_ACCEPT: (
        "observe",
        "replace_input",
        "deny",
        "add_metadata",
        "diagnostics",
    ),
    CHAT_BEFORE_MODEL_REQUEST: (
        "observe",
        "replace_messages",
        "replace_tools",
        "add_metadata",
        "diagnostics",
    ),
    CHAT_AFTER_MODEL_RESPONSE: ("observe", "add_metadata", "diagnostics"),
    TOOL_BEFORE_EXECUTE: (
        "observe",
        "replace_arguments",
        "deny",
        "handled",
        "add_metadata",
        "diagnostics",
    ),
    TOOL_AFTER_EXECUTE: (
        "observe",
        "replace_result",
        "add_metadata",
        "diagnostics",
    ),
    RUN_ON_ERROR: ("observe", "add_metadata", "diagnostics"),
}

EVENT_ALLOWED_ACTIONS = {
    INPUT_BEFORE_ACCEPT: ("continue", "deny"),
    CHAT_BEFORE_MODEL_REQUEST: ("continue",),
    CHAT_AFTER_MODEL_RESPONSE: ("continue",),
    TOOL_BEFORE_EXECUTE: ("continue", "deny", "handled"),
    TOOL_AFTER_EXECUTE: ("continue",),
    RUN_ON_ERROR: ("continue",),
}

EVENT_ALLOWED_FIELDS = {
    INPUT_BEFORE_ACCEPT: ("input", "metadata", "diagnostics", "reason"),
    CHAT_BEFORE_MODEL_REQUEST: ("messages", "tools", "metadata", "diagnostics"),
    CHAT_AFTER_MODEL_RESPONSE: ("metadata", "diagnostics"),
    TOOL_BEFORE_EXECUTE: ("arguments", "tool_result", "metadata", "diagnostics", "reason"),
    TOOL_AFTER_EXECUTE: ("tool_result", "metadata", "diagnostics"),
    RUN_ON_ERROR: ("metadata", "diagnostics"),
}

TOOL_EVENTS = frozenset({TOOL_BEFORE_EXECUTE, TOOL_AFTER_EXECUTE})


def is_supported_event(event: str) -> bool:
    return event in ALL_HOOK_EVENTS

