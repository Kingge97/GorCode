from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .context import HookContext, make_hook_context
from .events import ALL_HOOK_EVENTS, MESSAGE_REPLACE_EVENTS
from .protocols import HookRegistration
from .result import HookResult

DEFAULT_HOOK_PRIORITY = 0


class HookError(Exception):
    pass


class HookRegistrationError(HookError):
    pass


class HookExecutionError(HookError):
    pass


@dataclass(frozen=True)
class _StoredHook:
    registration: HookRegistration
    order: int


class HookManager:
    def __init__(self, hooks: list | tuple | None = None):
        self._hooks: dict[str, list[_StoredHook]] = {}
        self._next_order = 0
        self.register_many(hooks or [])

    def add_hook(
        self,
        event: str,
        handler,
        *,
        priority: int = DEFAULT_HOOK_PRIORITY,
        name: str | None = None,
    ) -> HookRegistration:
        registration = HookRegistration(event, handler, priority, name)
        return self.register(registration)

    def register(self, registration) -> HookRegistration:
        if self._is_object_hook(registration):
            return self._register_object_hook(registration)
        self._validate_registration(registration)
        stored = _StoredHook(registration, self._next_order)
        self._next_order += 1
        hooks = self._hooks.setdefault(registration.event, [])
        hooks.append(stored)
        hooks.sort(key=lambda item: (-item.registration.priority, item.order))
        return registration

    def register_many(self, hooks) -> None:
        for hook in hooks:
            self.register(hook)

    def remove_hook(self, event: str, handler_or_name) -> int:
        self._validate_event(event)
        hooks = self._hooks.get(event, [])
        remaining = [
            hook for hook in hooks
            if not self._matches_hook(hook.registration, handler_or_name)
        ]
        removed = len(hooks) - len(remaining)
        self._hooks[event] = remaining
        return removed

    def run(
        self,
        event: str,
        *,
        target_messages: list,
        router: str,
        model_name: str,
        loop_round: int,
        previous_round_had_tools: bool,
        tool_info: list | tuple | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._validate_run_input(event, target_messages)
        current_metadata = dict(metadata or {})
        for stored_hook in self._hooks.get(event, []):
            context = make_hook_context(
                event=event,
                router=router,
                model_name=model_name,
                messages=target_messages,
                loop_round=loop_round,
                previous_round_had_tools=previous_round_had_tools,
                tool_info=tool_info,
                metadata=current_metadata,
            )
            result = self._invoke(stored_hook.registration, context)
            self._apply_result(event, result, target_messages, current_metadata)
        return current_metadata

    def _register_object_hook(self, hook) -> HookRegistration:
        events = getattr(hook, "events", None)
        if not events:
            raise HookRegistrationError("Object hook must define non-empty events")
        last_registration = None
        for event in events:
            last_registration = self.add_hook(event, hook)
        return last_registration

    def _invoke(
        self,
        registration: HookRegistration,
        context: HookContext,
    ) -> HookResult | None:
        try:
            handler = registration.handler
            if hasattr(handler, "handle"):
                return handler.handle(context)
            return handler(context)
        except Exception as exc:
            name = self._hook_name(registration)
            message = (
                f"Hook '{name}' failed during event '{context.event}' "
                f"for router '{context.router}': {exc}"
            )
            raise HookExecutionError(message) from exc

    def _apply_result(
        self,
        event: str,
        result,
        target_messages: list,
        metadata: dict[str, Any],
    ) -> None:
        if result is None:
            return
        if not isinstance(result, HookResult):
            raise HookExecutionError("Hook handler must return HookResult or None")
        self._apply_metadata(result.metadata, metadata)
        if result.messages is None:
            return
        self._validate_message_replacement(event, result.messages)
        target_messages[:] = result.messages

    def _apply_metadata(self, result_metadata, metadata: dict[str, Any]) -> None:
        if not isinstance(result_metadata, Mapping):
            raise HookExecutionError("HookResult.metadata must be a mapping")
        metadata.update(dict(result_metadata))

    def _validate_message_replacement(self, event: str, messages) -> None:
        if event not in MESSAGE_REPLACE_EVENTS:
            raise HookExecutionError(
                f"Hook event '{event}' does not allow message replacement"
            )
        if not isinstance(messages, list):
            raise HookExecutionError("HookResult.messages must be a list[dict]")
        if not all(isinstance(message, dict) for message in messages):
            raise HookExecutionError("HookResult.messages must be a list[dict]")

    def _validate_run_input(self, event: str, target_messages) -> None:
        self._validate_event(event)
        if not isinstance(target_messages, list):
            raise HookExecutionError("target_messages must be a list")

    def _validate_registration(self, registration) -> None:
        if not isinstance(registration, HookRegistration):
            raise HookRegistrationError("Expected HookRegistration")
        self._validate_event(registration.event)
        if not self._is_valid_handler(registration.handler):
            raise HookRegistrationError("Hook handler must be callable or handle()")

    def _validate_event(self, event: str) -> None:
        if event not in ALL_HOOK_EVENTS:
            raise HookRegistrationError(f"Unsupported hook event: {event}")

    def _is_valid_handler(self, handler) -> bool:
        return callable(handler) or callable(getattr(handler, "handle", None))

    def _is_object_hook(self, hook) -> bool:
        return not isinstance(hook, HookRegistration) and hasattr(hook, "events")

    def _matches_hook(self, registration: HookRegistration, handler_or_name) -> bool:
        if isinstance(handler_or_name, str):
            return registration.name == handler_or_name
        return registration.handler is handler_or_name

    def _hook_name(self, registration: HookRegistration) -> str:
        if registration.name:
            return registration.name
        handler = registration.handler
        if hasattr(handler, "__name__"):
            return handler.__name__
        return handler.__class__.__name__
