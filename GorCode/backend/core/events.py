"""
Event System
============

Event-driven communication between frontend and backend.
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime
import asyncio


class EventType(Enum):
    """Event types for frontend-backend communication."""
    
    # Model events
    MODEL_THINKING = auto()      # Model is thinking
    MODEL_ANSWER = auto()        # Model answer content
    MODEL_TOOL_CALL = auto()     # Model tool call detected
    MODEL_END = auto()           # Model response ended
    MODEL_ERROR = auto()         # Model error occurred
    
    # Tool events
    TOOL_EXECUTION_START = auto()  # Tool execution started
    TOOL_EXECUTION_END = auto()    # Tool execution finished
    TOOL_RESULT = auto()           # Tool execution result
    
    # Agent events
    AGENT_SWITCH = auto()        # Agent switched
    AGENT_SUBAGENT_START = auto()  # Subagent started
    AGENT_SUBAGENT_END = auto()    # Subagent finished
    
    # Session events
    SESSION_NEW = auto()         # New session created
    SESSION_LOAD = auto()        # Session loaded
    SESSION_SAVE = auto()        # Session saved
    
    # UI events
    UI_MESSAGE = auto()          # UI message to display
    UI_CLEAR = auto()            # Clear UI
    UI_ANIMATION_START = auto()  # Animation started
    UI_ANIMATION_END = auto()    # Animation ended
    
    # Command events
    COMMAND_INPUT = auto()       # User command input
    COMMAND_OUTPUT = auto()      # Command output
    
    # Permission events
    PERMISSION_REQUEST = auto()  # Permission request from tool
    PERMISSION_RESPONSE = auto() # User response to permission request
    
    # System events
    SYSTEM_START = auto()        # System started
    SYSTEM_SHUTDOWN = auto()     # System shutdown
    SYSTEM_INTERRUPT = auto()    # System interrupted
    
    # User interaction events
    USER_REJECTION = auto()      # User rejected operation without reason


@dataclass
class Event:
    """Event data structure."""
    
    event_type: EventType
    data: Any = None
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "backend"  # "backend" or "frontend"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for serialization."""
        return {
            "event_type": self.event_type.name,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        """Create event from dictionary."""
        return cls(
            event_type=EventType[data["event_type"]],
            data=data["data"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            source=data.get("source", "backend"),
        )


class EventBus:
    """
    Event bus for frontend-backend communication.
    
    Implements a publish-subscribe pattern for loose coupling between components.
    """
    
    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = {}
        self._async_subscribers: Dict[EventType, List[Callable]] = {}
        self._event_queue: asyncio.Queue = None
    
    def subscribe(self, event_type: EventType, callback: Callable) -> None:
        """
        Subscribe to an event type.
        
        Args:
            event_type: Type of event to subscribe to
            callback: Callback function to execute when event is published
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
    
    def subscribe_async(self, event_type: EventType, callback: Callable) -> None:
        """
        Subscribe to an event type with an async callback.
        
        Args:
            event_type: Type of event to subscribe to
            callback: Async callback function to execute when event is published
        """
        if event_type not in self._async_subscribers:
            self._async_subscribers[event_type] = []
        self._async_subscribers[event_type].append(callback)
    
    def unsubscribe(self, event_type: EventType, callback: Callable) -> None:
        """
        Unsubscribe from an event type.
        
        Args:
            event_type: Type of event to unsubscribe from
            callback: Callback function to remove
        """
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                cb for cb in self._subscribers[event_type] if cb != callback
            ]
    
    def publish(self, event: Event) -> None:
        """
        Publish an event to all subscribers.
        
        Args:
            event: Event to publish
        """
        # Sync subscribers
        if event.event_type in self._subscribers:
            for callback in self._subscribers[event.event_type]:
                try:
                    callback(event)
                except Exception as e:
                    # Log error but don't stop event propagation
                    print(f"Error in event subscriber: {e}")
    
    async def publish_async(self, event: Event) -> None:
        """
        Publish an event to all subscribers (async version).
        
        Args:
            event: Event to publish
        """
        # Sync subscribers
        self.publish(event)
        
        # Async subscribers
        if event.event_type in self._async_subscribers:
            for callback in self._async_subscribers[event.event_type]:
                try:
                    await callback(event)
                except Exception as e:
                    print(f"Error in async event subscriber: {e}")
    
    def emit(self, event_type: EventType, data: Any = None, source: str = "backend") -> None:
        """
        Convenience method to emit an event.
        
        Args:
            event_type: Type of event to emit
            data: Event data
            source: Event source ("backend" or "frontend")
        """
        event = Event(event_type=event_type, data=data, source=source)
        self.publish(event)
    
    async def emit_async(self, event_type: EventType, data: Any = None, source: str = "backend") -> None:
        """
        Convenience method to emit an event (async version).
        
        Args:
            event_type: Type of event to emit
            data: Event data
            source: Event source ("backend" or "frontend")
        """
        event = Event(event_type=event_type, data=data, source=source)
        await self.publish_async(event)
