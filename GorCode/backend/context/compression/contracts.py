"""Public contracts for GorCode compression algorithms."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol


class CompressionError(Exception):
    """Base error for compression setup or execution failures."""


class CompressionConfigError(CompressionError):
    """Raised when compression configuration is invalid."""


@dataclass(frozen=True)
class CompressionRequest:
    """Input passed to builtin and external compression algorithms."""

    messages: tuple[dict, ...]
    context_limit: int
    threshold_ratio: float
    count_tokens: Callable[[list[dict]], int]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompressionResult:
    """Algorithm output consumed by GorCode."""

    messages: list[dict]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompressionRunResult:
    """Controller output for manual compression and diagnostics."""

    messages: list[dict]
    algorithm: str
    original_tokens: int
    compacted_tokens: int
    trigger_tokens: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def compression_ratio(self) -> float:
        if self.compacted_tokens == 0:
            return 0
        return self.original_tokens / self.compacted_tokens


class CompressionAlgorithm(Protocol):
    """Protocol implemented by loaded compression algorithms."""

    def compress(self, request: CompressionRequest) -> CompressionResult:
        """Compress request messages and return a CompressionResult."""
