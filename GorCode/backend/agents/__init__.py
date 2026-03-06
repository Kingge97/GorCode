"""
Agents Module
=============

Agent definitions and management including:
- Primary agents (build, plan)
- Sub-agents (explore, general)
- Agent prompts and permissions
- Agent loader for Markdown files
"""

from .base import (
    BaseAgent,
    AgentRegistry,
    AgentInfo,
    AgentMode,
    AgentPermission,
    PermissionLevel,
)
from .loader import AgentLoader

__all__ = [
    "BaseAgent",
    "AgentRegistry",
    "AgentInfo",
    "AgentMode",
    "AgentPermission",
    "PermissionLevel",
    "AgentLoader",
]
