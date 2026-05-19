"""Status payload builder for hooks."""

from __future__ import annotations

from typing import Any

from .config import HookSettings
from .events import ALL_HOOK_EVENTS, EVENT_CAPABILITIES


def build_hook_status(settings: HookSettings, loaded_ids: set[str]) -> dict[str, Any]:
    hooks = [_hook_status(config, config.id in loaded_ids) for config in settings.hooks]
    return {
        "enabled": settings.enabled,
        "hooks": hooks,
        "events": {
            event: {
                "hook_count": _count_loaded_for_event(settings, loaded_ids, event),
                "capabilities": list(EVENT_CAPABILITIES[event]),
            }
            for event in ALL_HOOK_EVENTS
        },
    }


def _hook_status(config, loaded: bool) -> dict[str, Any]:
    data = {
        "id": config.id,
        "enabled": config.enabled,
        "event": config.event,
        "type": config.type,
        "priority": config.priority,
        "timeout_seconds": config.timeout_seconds,
        "status": "loaded" if loaded else ("disabled" if not config.enabled else "not_loaded"),
        "scope": config.scope.to_dict(),
        "params_keys": sorted(str(key) for key in (config.params or {}).keys()),
    }
    target = _target(config)
    if target:
        data["target"] = target
    return data


def _target(config) -> str:
    if config.type == "http":
        return config.url or ""
    if config.type == "process":
        return config.command or ""
    if config.type == "python":
        return f"{config.module}:{config.factory}"
    if config.type == "builtin":
        return config.name or ""
    return ""


def _count_loaded_for_event(settings: HookSettings, loaded_ids: set[str], event: str) -> int:
    return sum(1 for hook in settings.hooks if hook.id in loaded_ids and hook.event == event)

