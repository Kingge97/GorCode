"""Parsing and validation for hook_settings."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from .errors import HookConfigError
from .events import ALL_HOOK_EVENTS, TOOL_EVENTS

DEFAULT_TIMEOUT_SECONDS = 30
HOOK_TYPES = {"builtin", "python", "process", "http"}
SOURCES = {"main", "subagent"}


def default_hook_settings_dict() -> dict[str, Any]:
    return {"enabled": True, "hooks": []}


@dataclass(frozen=True)
class HookScope:
    sources: tuple[str, ...] = ("main",)
    agents: Optional[tuple[str, ...]] = None
    subagent_types: Optional[tuple[str, ...]] = None
    tool_names: Optional[tuple[str, ...]] = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"sources": list(self.sources)}
        _add_optional_tuple(data, "agents", self.agents)
        _add_optional_tuple(data, "subagent_types", self.subagent_types)
        _add_optional_tuple(data, "tool_names", self.tool_names)
        return data

    def matches(
        self,
        *,
        source: str,
        agent_name: str,
        subagent_type: Optional[str],
        tool_name: Optional[str],
    ) -> bool:
        if source not in self.sources:
            return False
        if self.agents and agent_name not in self.agents:
            return False
        if self.subagent_types and subagent_type not in self.subagent_types:
            return False
        if self.tool_names and tool_name not in self.tool_names:
            return False
        return True


@dataclass(frozen=True)
class HookConfig:
    id: str
    enabled: bool = True
    event: Optional[str] = None
    type: Optional[str] = None
    priority: int = 0
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    scope: HookScope = field(default_factory=HookScope)
    params: Mapping[str, Any] = field(default_factory=dict)
    order: int = 0
    name: Optional[str] = None
    module: Optional[str] = None
    factory: Optional[str] = None
    command: Optional[str] = None
    url: Optional[str] = None


@dataclass(frozen=True)
class HookSettings:
    enabled: bool = True
    hooks: tuple[HookConfig, ...] = ()


def merge_hook_settings(
    base: Mapping[str, Any] | None,
    override: Mapping[str, Any] | None,
    *,
    override_present: bool = True,
) -> dict[str, Any]:
    result = copy.deepcopy(dict(base or default_hook_settings_dict()))
    if not override_present:
        return result
    data = dict(override or {})
    if "enabled" in data:
        result["enabled"] = bool(data["enabled"])
    if "hooks" in data:
        result["hooks"] = _merge_hooks_by_id(result.get("hooks", []), data.get("hooks", []))
    return result


def parse_hook_settings(raw: Mapping[str, Any] | None) -> HookSettings:
    data = default_hook_settings_dict()
    data.update(dict(raw or {}))
    hooks_raw = data.get("hooks") or []
    _ensure_unique_ids(hooks_raw)
    hooks = tuple(_parse_hook_config(item, index) for index, item in enumerate(hooks_raw))
    return HookSettings(enabled=bool(data.get("enabled", True)), hooks=hooks)


def _parse_hook_config(raw: Mapping[str, Any], order: int) -> HookConfig:
    if not isinstance(raw, Mapping):
        raise HookConfigError("hook_settings.hooks items must be objects")
    data = dict(raw)
    hook_id = _required_str(data, "id")
    enabled = bool(data.get("enabled", True))
    if not enabled:
        return HookConfig(
            id=hook_id,
            enabled=False,
            event=data.get("event"),
            type=data.get("type"),
            priority=data.get("priority", 0) if isinstance(data.get("priority", 0), int) else 0,
            timeout_seconds=(
                data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
                if isinstance(data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS), int)
                else DEFAULT_TIMEOUT_SECONDS
            ),
            params=data.get("params") if isinstance(data.get("params"), Mapping) else {},
            order=order,
            name=data.get("name"),
            module=data.get("module"),
            factory=data.get("factory"),
            command=data.get("command"),
            url=data.get("url"),
        )
    scope = _parse_scope(data.get("scope") or {}, data.get("event"))
    config = HookConfig(
        id=hook_id,
        enabled=enabled,
        event=data.get("event"),
        type=data.get("type"),
        priority=_parse_int(data.get("priority", 0), "priority"),
        timeout_seconds=_parse_timeout(data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
        scope=scope,
        params=_parse_params(data.get("params") or {}),
        order=order,
        name=data.get("name"),
        module=data.get("module"),
        factory=data.get("factory"),
        command=data.get("command"),
        url=data.get("url"),
    )
    _validate_enabled_config(config)
    return config


def _parse_scope(raw: Mapping[str, Any], event: Optional[str]) -> HookScope:
    if not isinstance(raw, Mapping):
        raise HookConfigError("scope must be an object")
    sources = tuple(raw.get("sources", ["main"]))
    if not sources:
        raise HookConfigError("scope.sources must not be empty")
    if any(source not in SOURCES for source in sources):
        raise HookConfigError("scope.sources must contain only main/subagent")
    tool_names = _optional_str_tuple(raw, "tool_names")
    if tool_names and event not in TOOL_EVENTS:
        raise HookConfigError("scope.tool_names is only allowed for tool events")
    return HookScope(
        sources=sources,
        agents=_optional_str_tuple(raw, "agents"),
        subagent_types=_optional_str_tuple(raw, "subagent_types"),
        tool_names=tool_names,
    )


def _validate_enabled_config(config: HookConfig) -> None:
    if not config.enabled:
        return
    if config.event not in ALL_HOOK_EVENTS:
        raise HookConfigError(f"Unsupported hook event: {config.event}")
    if config.type not in HOOK_TYPES:
        raise HookConfigError(f"Unsupported hook type: {config.type}")
    if config.type == "builtin" and not _is_nonempty_str(config.name):
        raise HookConfigError(f"builtin hook '{config.id}' requires name")
    if config.type == "python" and not _is_nonempty_str(config.module):
        raise HookConfigError(f"python hook '{config.id}' requires module")
    if config.type == "python" and not _is_nonempty_str(config.factory):
        raise HookConfigError(f"python hook '{config.id}' requires factory")
    if config.type == "process" and not _is_nonempty_str(config.command):
        raise HookConfigError(f"process hook '{config.id}' requires command")
    if config.type == "http" and not _is_nonempty_str(config.url):
        raise HookConfigError(f"http hook '{config.id}' requires url")


def _merge_hooks_by_id(base_hooks: Sequence[Any], override_hooks: Sequence[Any]) -> list[dict[str, Any]]:
    _ensure_unique_ids(override_hooks)
    merged = [copy.deepcopy(dict(item)) for item in base_hooks]
    index = {item["id"]: pos for pos, item in enumerate(merged) if "id" in item}
    for item in override_hooks:
        hook = copy.deepcopy(dict(item))
        hook_id = hook.get("id")
        if hook_id in index:
            merged[index[hook_id]] = hook
        else:
            index[hook_id] = len(merged)
            merged.append(hook)
    return merged


def _ensure_unique_ids(hooks: Sequence[Any]) -> None:
    seen: set[str] = set()
    for item in hooks:
        if not isinstance(item, Mapping):
            raise HookConfigError("hook_settings.hooks items must be objects")
        hook_id = _required_str(dict(item), "id")
        if hook_id in seen:
            raise HookConfigError(f"Duplicate hook id in same layer: {hook_id}")
        seen.add(hook_id)


def _optional_str_tuple(raw: Mapping[str, Any], key: str) -> Optional[tuple[str, ...]]:
    if key not in raw:
        return None
    value = raw[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise HookConfigError(f"scope.{key} must be list[str]")
    return tuple(value)


def _required_str(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not _is_nonempty_str(value):
        raise HookConfigError(f"hook {key} is required")
    return str(value)


def _parse_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HookConfigError(f"{name} must be int")
    return value


def _parse_timeout(value: Any) -> int:
    timeout = _parse_int(value, "timeout_seconds")
    if timeout <= 0:
        raise HookConfigError("timeout_seconds must be positive")
    return timeout


def _parse_params(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HookConfigError("params must be an object")
    return dict(value)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _add_optional_tuple(data: dict[str, Any], key: str, value: Optional[tuple[str, ...]]) -> None:
    if value is not None:
        data[key] = list(value)
