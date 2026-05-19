from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class HookResult:
    messages: list[dict] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
