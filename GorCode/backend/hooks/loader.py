"""Hook loader implementations."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .builtin import BUILTIN_HOOK_FACTORIES
from .config import HookConfig
from .context import HookContext
from .errors import HookConfigError
from .result import HookResult
from .transports import call_http_hook, call_process_hook


@dataclass(frozen=True)
class LoadedHook:
    id: str
    config: HookConfig
    handler: Any
    status: str = "loaded"


class ProcessHookHandler:
    def __init__(self, config: HookConfig):
        self.config = config

    def handle(self, context: HookContext) -> HookResult | dict | None:
        return call_process_hook(
            command=str(self.config.command),
            timeout_seconds=self.config.timeout_seconds,
            hook_id=self.config.id,
            params=self.config.params,
            context=context,
        )


class HttpHookHandler:
    def __init__(self, config: HookConfig):
        self.config = config

    def handle(self, context: HookContext) -> HookResult | dict | None:
        return call_http_hook(
            url=str(self.config.url),
            timeout_seconds=self.config.timeout_seconds,
            hook_id=self.config.id,
            params=self.config.params,
            context=context,
        )


def load_hook(config: HookConfig) -> Optional[LoadedHook]:
    if not config.enabled:
        return None
    if config.type == "builtin":
        handler = _load_builtin(config)
    elif config.type == "python":
        handler = _load_python(config)
    elif config.type == "process":
        handler = ProcessHookHandler(config)
    elif config.type == "http":
        handler = HttpHookHandler(config)
    else:
        raise HookConfigError(f"Unsupported hook type: {config.type}")
    _validate_handler(config.id, handler)
    return LoadedHook(id=config.id, config=config, handler=handler)


def load_hooks(configs: tuple[HookConfig, ...]) -> tuple[LoadedHook, ...]:
    loaded: list[LoadedHook] = []
    for config in configs:
        hook = load_hook(config)
        if hook is not None:
            loaded.append(hook)
    return tuple(loaded)


def _load_builtin(config: HookConfig) -> Any:
    factory = BUILTIN_HOOK_FACTORIES.get(str(config.name))
    if not factory:
        raise HookConfigError(f"Unknown builtin hook name: {config.name}")
    return _call_factory(factory, config)


def _load_python(config: HookConfig) -> Any:
    try:
        module = importlib.import_module(str(config.module))
    except Exception as exc:
        raise HookConfigError(f"Failed to import hook module '{config.module}': {exc}") from exc
    factory = getattr(module, str(config.factory), None)
    if not callable(factory):
        raise HookConfigError(f"Hook factory '{config.factory}' is not callable")
    return _call_factory(factory, config)


def _call_factory(factory: Callable[..., Any], config: HookConfig) -> Any:
    try:
        return factory(**dict(config.params or {}))
    except TypeError as exc:
        raise HookConfigError(f"Hook factory for '{config.id}' failed: {exc}") from exc


def _validate_handler(hook_id: str, handler: Any) -> None:
    if callable(handler) or callable(getattr(handler, "handle", None)):
        return
    raise HookConfigError(f"Hook '{hook_id}' must be callable or implement handle(context)")

