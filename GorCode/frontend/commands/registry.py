"""
Command registry
================

Single source of truth for CLI commands and help entries.
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class CommandSpec:
    """Command metadata for routing and help rendering."""

    keys: Tuple[str, ...]
    handler: str
    help_entries: Tuple[Tuple[str, str], ...]


COMMAND_SPECS: Tuple[CommandSpec, ...] = (
    CommandSpec(("help",), "_cmd_help", (("/help", "Show this help message"),)),
    CommandSpec(
        ("agent",),
        "_cmd_agent",
        (("/agent <name>", "Switch to a different agent (build, plan)"),),
    ),
    CommandSpec(("model",), "_cmd_model", (("/model <name>", "Switch to a different model"),)),
    CommandSpec((
        "init",
    ), "_cmd_init", (("/init", "Initialize GorCode in the current directory"),)),
    CommandSpec(("mcps",), "_cmd_mcps", (("/mcps", "Manage MCP servers"),)),
    CommandSpec(("skills",), "_cmd_skills", (("/skills", "Manage skills"),)),
    CommandSpec(("new",), "_cmd_new", (("/new", "Start a new session"),)),
    CommandSpec(
        ("history",),
        "_cmd_history",
        (
            ("/history list", "List session history"),
            ("/history load <id>", "Load a session from history"),
            ("/history search <query>", "Search session history"),
        ),
    ),
    CommandSpec((
        "debug",
    ), "_cmd_debug", (("/debug on|off|status", "Control debug mode"),)),
    CommandSpec(
        ("compact",),
        "_cmd_compact",
        (("/compact [--soft|--hard|--status]", "Compact conversation context"),),
    ),
    CommandSpec(("context",), "_cmd_context", (("/context status|stats", "View context and cache statistics"),)),
    CommandSpec(
        ("permission",),
        "_cmd_permission",
        (("/permission [status|grant|revoke|clear]", "Manage session permissions"),),
    ),
    CommandSpec(("exit", "quit"), "_cmd_exit", (("/exit", "Exit GorCode"),)),
)
