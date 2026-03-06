"""
Backend Module
==============

Core backend functionality including:
- Model connection and chat loop
- Agent management
- Tool execution
- Configuration management
"""

from .core.events import EventBus, Event, EventType
from .core.executor import BackendExecutor

__all__ = ["EventBus", "Event", "EventType", "BackendExecutor"]
