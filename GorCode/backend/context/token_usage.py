"""
Real provider token usage aggregation.

This module tracks API usage reported by providers. It must not estimate usage
from message history.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping


INPUT_TOKENS = "input_tokens"
OUTPUT_TOKENS = "output_tokens"
TOTAL_TOKENS = "total_tokens"
SESSION_INPUT_TOKENS = "session_input_tokens"
SESSION_OUTPUT_TOKENS = "session_output_tokens"
SESSION_TOTAL_TOKENS = "session_total_tokens"
USAGE_KEYS = (INPUT_TOKENS, OUTPUT_TOKENS, TOTAL_TOKENS)


@dataclass(frozen=True)
class TokenUsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TokenUsageTotals":
        usage = normalize_usage_payload(data)
        return cls(
            input_tokens=usage[INPUT_TOKENS],
            output_tokens=usage[OUTPUT_TOKENS],
            total_tokens=usage[TOTAL_TOKENS],
        )

    def add_usage(self, usage: Mapping[str, Any]) -> "TokenUsageTotals":
        normalized = normalize_usage_payload(usage)
        input_tokens = self.input_tokens + normalized[INPUT_TOKENS]
        output_tokens = self.output_tokens + normalized[OUTPUT_TOKENS]
        return TokenUsageTotals(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )

    def to_dict(self) -> Dict[str, int]:
        return {
            INPUT_TOKENS: self.input_tokens,
            OUTPUT_TOKENS: self.output_tokens,
            TOTAL_TOKENS: self.total_tokens,
        }

    def to_session_payload(self) -> Dict[str, int]:
        return {
            SESSION_INPUT_TOKENS: self.input_tokens,
            SESSION_OUTPUT_TOKENS: self.output_tokens,
            SESSION_TOTAL_TOKENS: self.total_tokens,
        }


def empty_token_usage_dict() -> Dict[str, int]:
    return {INPUT_TOKENS: 0, OUTPUT_TOKENS: 0, TOTAL_TOKENS: 0}


def normalize_usage_payload(data: Mapping[str, Any]) -> Dict[str, int]:
    if not isinstance(data, Mapping):
        raise TypeError("usage payload must be a mapping")

    usage = {key: _read_token(data, key) for key in USAGE_KEYS}
    return usage


def _read_token(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"usage field {key} must be an integer")
    if value < 0:
        raise ValueError(f"usage field {key} must be non-negative")
    return value
