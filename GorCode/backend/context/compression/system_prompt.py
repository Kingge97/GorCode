"""System message hiding, restoration, and validation."""

from __future__ import annotations

import copy
from dataclasses import dataclass

from .contracts import CompressionError

SYSTEM_MESSAGE_PLACEHOLDER = {
    "role": "system",
    "content": "[System prompt hidden by GorCode before compression.]",
    "_gorcode_hidden_system": True,
}


@dataclass(frozen=True)
class HiddenSystemState:
    messages: list[dict]
    original_system_message: dict | None


def hide_system_message(messages: list[dict]) -> HiddenSystemState:
    """Hide the leading system message before passing messages to algorithms."""
    copied = [copy.deepcopy(message) for message in messages]
    original = None
    if copied and copied[0].get("role") == "system":
        original = copy.deepcopy(copied[0])
        copied[0] = copy.deepcopy(SYSTEM_MESSAGE_PLACEHOLDER)
    return HiddenSystemState(messages=copied, original_system_message=original)


def restore_system_message(
    state: HiddenSystemState,
    result_messages: list[dict],
) -> list[dict]:
    """Restore the original leading system message after compression."""
    restored = [copy.deepcopy(message) for message in result_messages]
    original = state.original_system_message
    if original is None:
        return restored
    if restored and restored[0].get("role") == "system":
        restored[0] = copy.deepcopy(original)
        return restored
    return [copy.deepcopy(original), *restored]


def validate_system_message_position(messages: list[dict]) -> None:
    """Ensure system messages only appear at index 0."""
    for index, message in enumerate(messages):
        if message.get("role") != "system":
            continue
        if index != 0:
            raise CompressionError("system message is only allowed at position 0")
