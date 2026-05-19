"""Errors for the GorCode application hook subsystem."""


class HookError(Exception):
    """Base class for GorCode hook errors."""


class HookConfigError(HookError):
    """Raised when hook configuration is invalid."""


class HookRegistrationError(HookError):
    """Raised when a hook cannot be registered."""


class HookExecutionError(HookError):
    """Raised when hook execution fails."""


class HookProtocolError(HookExecutionError):
    """Raised when a process/http hook violates gorcode-hook-v1."""


class HookTimeoutError(HookExecutionError):
    """Raised when a process/http hook times out."""

