from enum import Enum


class HookEvent(str, Enum):
    BEFORE_LOOP_START = "before_loop_start"
    BEFORE_MODEL_REQUEST = "before_model_request"
    AFTER_MODEL_RESPONSE = "after_model_response"
    BEFORE_TOOL_EXECUTION = "before_tool_execution"
    AFTER_TOOL_EXECUTION = "after_tool_execution"
    BEFORE_NEXT_LOOP = "before_next_loop"
    AFTER_LOOP_END = "after_loop_end"
    ON_ERROR = "on_error"
    ON_INTERRUPT = "on_interrupt"


ALL_HOOK_EVENTS = frozenset(event.value for event in HookEvent)

MESSAGE_REPLACE_EVENTS = frozenset({
    HookEvent.BEFORE_LOOP_START.value,
    HookEvent.BEFORE_MODEL_REQUEST.value,
    HookEvent.AFTER_TOOL_EXECUTION.value,
    HookEvent.BEFORE_NEXT_LOOP.value,
})
