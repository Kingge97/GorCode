"""GorCode application hook subsystem."""

from .config import HookConfig, HookScope, HookSettings, default_hook_settings_dict
from .context import HookContext
from .errors import (
    HookConfigError,
    HookError,
    HookExecutionError,
    HookProtocolError,
    HookRegistrationError,
    HookTimeoutError,
)
from .events import (
    CHAT_AFTER_MODEL_RESPONSE,
    CHAT_BEFORE_MODEL_REQUEST,
    INPUT_BEFORE_ACCEPT,
    RUN_ON_ERROR,
    TOOL_AFTER_EXECUTE,
    TOOL_BEFORE_EXECUTE,
)
from .result import HookResult
from .runtime import HookRuntime, ToolBeforeHookResult, make_call_base

__all__ = [
    "CHAT_AFTER_MODEL_RESPONSE",
    "CHAT_BEFORE_MODEL_REQUEST",
    "HookConfig",
    "HookConfigError",
    "HookContext",
    "HookError",
    "HookExecutionError",
    "HookProtocolError",
    "HookRegistrationError",
    "HookResult",
    "HookRuntime",
    "HookScope",
    "HookSettings",
    "HookTimeoutError",
    "INPUT_BEFORE_ACCEPT",
    "RUN_ON_ERROR",
    "TOOL_AFTER_EXECUTE",
    "TOOL_BEFORE_EXECUTE",
    "ToolBeforeHookResult",
    "default_hook_settings_dict",
    "make_call_base",
]

