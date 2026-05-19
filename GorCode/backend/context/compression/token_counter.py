"""Token counting utilities for compression."""

from __future__ import annotations

from ..token_estimator import TokenEstimator


def default_count_tokens(messages: list[dict]) -> int:
    """Estimate tokens for a list of messages."""
    return TokenEstimator.estimate_messages(messages)
