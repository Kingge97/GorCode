"""
Commands Module
===============

User command handlers for CLI.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .handler import CommandHandler


def __getattr__(name: str):
    if name == "CommandHandler":
        from .handler import CommandHandler  # Local import to avoid circular deps
        return CommandHandler
    raise AttributeError(name)


__all__ = ["CommandHandler"]
