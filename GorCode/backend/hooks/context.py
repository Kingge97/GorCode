"""Immutable hook context exposed to GorCode application hooks."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Optional


def freeze_value(value: Any) -> Any:
    """Recursively freeze containers so hook handlers cannot mutate context."""
    copied = copy.deepcopy(value)
    return _freeze_copied(copied)


def _freeze_copied(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze_copied(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_copied(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_copied(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_copied(item) for item in value)
    return value


def thaw_value(value: Any) -> Any:
    """Convert frozen containers back to plain JSON-like containers."""
    if isinstance(value, Mapping):
        return {str(k): thaw_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw_value(item) for item in value]
    if isinstance(value, frozenset):
        return [thaw_value(item) for item in value]
    return value


@dataclass(frozen=True)
class HookContext:
    """Context passed to a GorCode application hook."""

    event: str
    run_id: str
    hook_run_id: str
    session_id: Optional[str]
    source: str
    agent_name: str
    agent_run_id: Optional[str]
    parent_agent: Optional[str]
    subagent_type: Optional[str]
    model_name: Optional[str]
    workspace_root: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    system_metadata: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", freeze_value(self.payload))
        object.__setattr__(self, "system_metadata", freeze_value(self.system_metadata))
        object.__setattr__(self, "metadata", freeze_value(self.metadata))

    def to_protocol_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "run_id": self.run_id,
            "hook_run_id": self.hook_run_id,
            "session_id": self.session_id,
            "source": self.source,
            "agent_name": self.agent_name,
            "agent_run_id": self.agent_run_id,
            "parent_agent": self.parent_agent,
            "subagent_type": self.subagent_type,
            "model_name": self.model_name,
            "workspace_root": self.workspace_root,
            "payload": thaw_value(self.payload),
            "system_metadata": thaw_value(self.system_metadata),
            "metadata": thaw_value(self.metadata),
        }

