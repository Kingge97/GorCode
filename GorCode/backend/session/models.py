"""
Session Models
==============

Data models for session management.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path
import json
import uuid

from ..utils.serialization import dataclass_from_dict, dataclass_to_dict, parse_datetime


@dataclass
class SessionMetadata:
    """Metadata for a session."""
    
    session_id: str
    title: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    agent: str = "build"
    model: str = "main"
    message_count: int = 0
    project_path: str = ""
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return dataclass_to_dict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionMetadata":
        """Create from dictionary."""
        return dataclass_from_dict(
            cls,
            data,
            field_deserializers={
                "created_at": lambda value: parse_datetime(value, datetime.now()),
                "updated_at": lambda value: parse_datetime(value, datetime.now()),
            },
            field_defaults={
                "session_id": lambda: str(uuid.uuid4()),
            },
        )


@dataclass
class Session:
    """
    Represents a conversation session.
    
    A session contains:
    - Metadata (id, title, timestamps, etc.)
    - Message history
    - Current state
    """
    
    metadata: SessionMetadata
    messages: List[Dict[str, Any]] = field(default_factory=list)
    
    @property
    def session_id(self) -> str:
        """Get session ID."""
        return self.metadata.session_id
    
    @property
    def title(self) -> str:
        """Get session title."""
        return self.metadata.title
    
    @title.setter
    def title(self, value: str) -> None:
        """Set session title."""
        self.metadata.title = value
        self.metadata.updated_at = datetime.now()
    
    def add_message(self, role: str, content: Any, **kwargs) -> None:
        """
        Add a message to the session.
        
        Args:
            role: Message role (user, assistant, system)
            content: Message content
            **kwargs: Additional message fields
        """
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self.messages.append(message)
        self.metadata.message_count = len(self.messages)
        self.metadata.updated_at = datetime.now()
    
    def get_messages_for_model(self) -> List[Dict[str, Any]]:
        """
        Get messages formatted for model API.
        
        Returns:
            List of messages without internal fields
        """
        result = []
        for msg in self.messages:
            # Remove internal fields
            model_msg = {
                "role": msg["role"],
                "content": msg["content"],
            }
            # Add tool_calls if present
            if "tool_calls" in msg:
                model_msg["tool_calls"] = msg["tool_calls"]
            if "tool_call_id" in msg:
                model_msg["tool_call_id"] = msg["tool_call_id"]
            result.append(model_msg)
        return result
    
    def clear_messages(self) -> None:
        """Clear all messages."""
        self.messages = []
        self.metadata.message_count = 0
        self.metadata.updated_at = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert session to dictionary."""
        return dataclass_to_dict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        """Create session from dictionary."""
        return dataclass_from_dict(
            cls,
            data,
            field_deserializers={
                "metadata": lambda value: SessionMetadata.from_dict(value or {}),
            },
            field_defaults={
                "metadata": lambda: SessionMetadata.from_dict({}),
            },
        )
    
    @classmethod
    def create_new(
        cls,
        agent: str = "build",
        model: str = "main",
        project_path: str = "",
        title: str = "",
    ) -> "Session":
        """
        Create a new session.
        
        Args:
            agent: Initial agent name
            model: Initial model name
            project_path: Project path
            title: Session title
            
        Returns:
            New Session instance
        """
        session_id = str(uuid.uuid4())[:8]  # Short ID for readability
        metadata = SessionMetadata(
            session_id=session_id,
            title=title,
            agent=agent,
            model=model,
            project_path=project_path,
        )
        return cls(metadata=metadata)
    
    def generate_title(self) -> str:
        """
        Generate a title from the first user message.
        
        Returns:
            Generated title
        """
        if self.metadata.title:
            return self.metadata.title
        
        # Find first user message
        for msg in self.messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                # Use first 50 characters as title
                if isinstance(content, str):
                    title = content[:50].strip()
                    if len(content) > 50:
                        title += "..."
                    return title
                break
        
        return f"Session {self.session_id}"


@dataclass
class SessionSearchResult:
    """Result of a session search."""
    
    session_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    agent: str
    preview: str = ""  # First user message preview
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return dataclass_to_dict(self)
