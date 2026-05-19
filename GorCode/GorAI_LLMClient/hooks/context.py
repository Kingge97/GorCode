import copy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class HookContext:
    event: str
    router: str
    model_name: str
    messages: tuple[dict, ...]
    loop_round: int
    previous_round_had_tools: bool
    tool_info: tuple[dict, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)


def make_hook_context(
    *,
    event: str,
    router: str,
    model_name: str,
    messages: list,
    loop_round: int,
    previous_round_had_tools: bool,
    tool_info: list | tuple | None,
    metadata: Mapping[str, Any] | None,
) -> HookContext:
    return HookContext(
        event=event,
        router=router,
        model_name=model_name,
        messages=tuple(copy.deepcopy(messages)),
        loop_round=loop_round,
        previous_round_had_tools=previous_round_had_tools,
        tool_info=tuple(copy.deepcopy(tool_info or [])),
        metadata=MappingProxyType(copy.deepcopy(dict(metadata or {}))),
    )
