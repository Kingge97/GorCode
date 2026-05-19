from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from .context import HookContext
from .result import HookResult


HookHandler = Callable[[HookContext], HookResult | None]


class LLMClientHook(Protocol):
    events: Sequence[str]

    def handle(self, context: HookContext) -> HookResult | None:
        ...


@dataclass(frozen=True)
class HookRegistration:
    event: str
    handler: HookHandler | LLMClientHook
    priority: int = 0
    name: str | None = None
