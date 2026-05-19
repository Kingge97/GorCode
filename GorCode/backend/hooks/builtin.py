"""Fixed builtin hook registry."""

from __future__ import annotations

from typing import Callable

from .context import HookContext
from .result import HookResult


class DebugTraceHook:
    """Small diagnostic builtin useful for status and smoke tests."""

    def __init__(self, namespace: str = "debug_trace"):
        self.namespace = namespace

    def handle(self, context: HookContext) -> HookResult:
        return HookResult(
            metadata={
                self.namespace: {
                    "event": context.event,
                    "source": context.source,
                }
            }
        )


def create_debug_trace_hook(**params):
    namespace = str(params.get("namespace", "debug_trace"))
    return DebugTraceHook(namespace=namespace)


BUILTIN_HOOK_FACTORIES: dict[str, Callable[..., object]] = {
    "debug_trace": create_debug_trace_hook,
}

