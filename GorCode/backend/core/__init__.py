"""
Core Module
===========

Core backend functionality including event bus, executor, and model connector.
"""

from .events import EventBus, Event, EventType
from .executor import BackendExecutor, BackendState
from .model_connector import ModelConnector, ModelManager

__all__ = [
    "EventBus", 
    "Event", 
    "EventType", 
    "BackendExecutor", 
    "BackendState",
    "ModelConnector", 
    "ModelManager"
]
