"""
Session Manager
===============

Manages session lifecycle and coordinates with backend executor.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
import threading

from .models import Session, SessionMetadata, SessionSearchResult
from .storage import SessionStorage
from ..core.events import EventBus, Event, EventType


class SessionManager:
    """
    Manages session lifecycle.
    
    Responsibilities:
    - Create and destroy sessions
    - Save and load sessions
    - Auto-save functionality
    - Session state tracking
    - Integration with BackendExecutor
    """
    
    AUTOSAVE_INTERVAL = 60  # seconds
    AUTOSAVE_MESSAGE_THRESHOLD = 5  # save after N messages
    
    def __init__(
        self,
        event_bus: EventBus = None,
        storage: SessionStorage = None,
        project_path: str = "",
    ):
        """
        Initialize session manager.
        
        Args:
            event_bus: Event bus for communication
            storage: Session storage backend
            project_path: Current project path
        """
        self.event_bus = event_bus or EventBus()
        self.storage = storage or SessionStorage()
        self.project_path = project_path
        
        self._current_session: Optional[Session] = None
        self._message_count_since_save = 0
        self._autosave_timer: Optional[threading.Timer] = None
        self._autosave_enabled = True
        
        # Subscribe to events
        self._setup_event_handlers()
    
    def _setup_event_handlers(self) -> None:
        """Set up event handlers for auto-save."""
        # Will be connected to executor events
        pass
    
    # ========================
    # Current Session Management
    # ========================
    
    @property
    def current_session(self) -> Optional[Session]:
        """Get current session."""
        return self._current_session
    
    @property
    def has_session(self) -> bool:
        """Check if there is an active session."""
        return self._current_session is not None
    
    def create_session(
        self,
        agent: str = "build",
        model: str = "main",
        title: str = "",
    ) -> Session:
        """
        Create a new session.
        
        Args:
            agent: Initial agent name
            model: Initial model name
            title: Session title
            
        Returns:
            Newly created session
        """
        # Save current session if exists
        if self._current_session:
            self.save_current_session()
        
        # Create new session
        self._current_session = Session.create_new(
            agent=agent,
            model=model,
            project_path=self.project_path,
            title=title,
        )
        
        self._message_count_since_save = 0
        
        # Emit event
        self.event_bus.emit(EventType.SESSION_NEW, {
            "session_id": self._current_session.session_id,
        })
        
        # Start autosave timer
        self._start_autosave_timer()
        
        return self._current_session
    
    def load_session(self, session_id: str) -> Optional[Session]:
        """
        Load an existing session.
        
        Args:
            session_id: Session ID to load
            
        Returns:
            Loaded session or None if not found
        """
        # Save current session if exists
        if self._current_session:
            self.save_current_session()
        
        # Load session
        session = self.storage.load(session_id)
        if session:
            self._current_session = session
            self._message_count_since_save = 0
            
            # Emit event
            self.event_bus.emit(EventType.SESSION_LOAD, {
                "session_id": session_id,
                "message_count": len(session.messages),
            })
            
            # Start autosave timer
            self._start_autosave_timer()
        
        return session
    
    def close_session(self) -> bool:
        """
        Close the current session.
        
        Returns:
            True if session was closed successfully
        """
        if not self._current_session:
            return False
        
        # Stop autosave
        self._stop_autosave_timer()
        
        # Save final state
        self.save_current_session()
        
        self._current_session = None
        self._message_count_since_save = 0
        
        return True
    
    # ========================
    # Message Management
    # ========================
    
    def add_message(
        self,
        role: str,
        content: Any,
        **kwargs
    ) -> None:
        """
        Add a message to the current session.
        
        Args:
            role: Message role
            content: Message content
            **kwargs: Additional message fields
        """
        if not self._current_session:
            self.create_session()
        
        self._current_session.add_message(role, content, **kwargs)
        self._message_count_since_save += 1
        
        # Check if we should autosave
        if self._message_count_since_save >= self.AUTOSAVE_MESSAGE_THRESHOLD:
            self.save_current_session()
    
    def get_messages(self) -> List[Dict[str, Any]]:
        """
        Get messages from current session.
        
        Returns:
            List of messages
        """
        if self._current_session:
            return self._current_session.get_messages_for_model()
        return []
    
    def get_messages_raw(self) -> List[Dict[str, Any]]:
        """
        Get raw messages from current session (with metadata).
        
        Returns:
            List of messages with metadata
        """
        if self._current_session:
            return self._current_session.messages.copy()
        return []
    
    def set_messages(self, messages: List[Dict[str, Any]]) -> None:
        """
        Set messages in current session.
        
        Args:
            messages: Messages to set
        """
        if self._current_session:
            self._current_session.messages = messages
            self._current_session.metadata.message_count = len(messages)
            self._current_session.metadata.updated_at = datetime.now()
            
            # Always save when messages are set to ensure data persistence
            self.save_current_session()
    
    def clear_messages(self) -> None:
        """Clear messages in current session."""
        if self._current_session:
            self._current_session.clear_messages()
            self._message_count_since_save = 0
    
    # ========================
    # State Management
    # ========================
    
    def update_agent(self, agent: str) -> None:
        """
        Update current agent in session.
        
        Args:
            agent: Agent name
        """
        if self._current_session:
            self._current_session.metadata.agent = agent
            self._current_session.metadata.updated_at = datetime.now()
    
    def update_model(self, model: str) -> None:
        """
        Update current model in session.
        
        Args:
            model: Model name
        """
        if self._current_session:
            self._current_session.metadata.model = model
            self._current_session.metadata.updated_at = datetime.now()
    
    def set_title(self, title: str) -> None:
        """
        Set session title.
        
        Args:
            title: New title
        """
        if self._current_session:
            self._current_session.title = title
    
    def auto_generate_title(self) -> str:
        """
        Auto-generate title from first message.
        
        Returns:
            Generated title
        """
        if self._current_session:
            title = self._current_session.generate_title()
            self._current_session.title = title
            return title
        return ""
    
    # ========================
    # Persistence
    # ========================
    
    def save_current_session(self) -> bool:
        """
        Save the current session.
        
        Returns:
            True if successful
        """
        if not self._current_session:
            return False
        
        # Auto-generate title if not set
        if not self._current_session.title:
            self._current_session.title = self._current_session.generate_title()
        
        success = self.storage.save(self._current_session)
        
        if success:
            self._message_count_since_save = 0
            self.event_bus.emit(EventType.SESSION_SAVE, {
                "session_id": self._current_session.session_id,
            })
        
        return success
    
    def _start_autosave_timer(self) -> None:
        """Start autosave timer."""
        self._stop_autosave_timer()
        
        if self._autosave_enabled:
            self._autosave_timer = threading.Timer(
                self.AUTOSAVE_INTERVAL,
                self._autosave_callback
            )
            self._autosave_timer.daemon = True
            self._autosave_timer.start()
    
    def _stop_autosave_timer(self) -> None:
        """Stop autosave timer."""
        if self._autosave_timer:
            self._autosave_timer.cancel()
            self._autosave_timer = None
    
    def _autosave_callback(self) -> None:
        """Autosave callback."""
        if self._current_session and self._message_count_since_save > 0:
            self.save_current_session()
        
        # Restart timer
        self._start_autosave_timer()
    
    def set_autosave(self, enabled: bool) -> None:
        """
        Enable or disable autosave.
        
        Args:
            enabled: Whether to enable autosave
        """
        self._autosave_enabled = enabled
        if enabled and self._current_session:
            self._start_autosave_timer()
        else:
            self._stop_autosave_timer()
    
    # ========================
    # History and Search
    # ========================
    
    def list_sessions(
        self,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "updated_at",
    ) -> List[SessionSearchResult]:
        """
        List recent sessions.
        
        Args:
            limit: Maximum results
            offset: Pagination offset
            sort_by: Sort field
            
        Returns:
            List of session search results
        """
        return self.storage.list_sessions(
            limit=limit,
            offset=offset,
            sort_by=sort_by,
        )
    
    def search_sessions(
        self,
        query: str,
        limit: int = 10,
    ) -> List[SessionSearchResult]:
        """
        Search sessions.
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of matching sessions
        """
        return self.storage.search(query, limit)
    
    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.
        
        Args:
            session_id: Session ID to delete
            
        Returns:
            True if successful
        """
        # Don't delete current session
        if self._current_session and self._current_session.session_id == session_id:
            return False
        
        return self.storage.delete(session_id)
    
    def get_session_count(self) -> int:
        """Get total session count."""
        return self.storage.count()
    
    # ========================
    # Utility Methods
    # ========================
    
    def get_session_info(self) -> Dict[str, Any]:
        """
        Get information about current session.
        
        Returns:
            Session info dictionary
        """
        if not self._current_session:
            return {"active": False}
        
        return {
            "active": True,
            "session_id": self._current_session.session_id,
            "title": self._current_session.title,
            "agent": self._current_session.metadata.agent,
            "model": self._current_session.metadata.model,
            "message_count": len(self._current_session.messages),
            "created_at": self._current_session.metadata.created_at.isoformat(),
            "updated_at": self._current_session.metadata.updated_at.isoformat(),
        }
    
    def export_session(self, session_id: str = None) -> Optional[Dict[str, Any]]:
        """
        Export a session to dictionary.
        
        Args:
            session_id: Session ID (uses current if None)
            
        Returns:
            Session data or None
        """
        if session_id:
            session = self.storage.load(session_id)
        else:
            session = self._current_session
        
        if session:
            return session.to_dict()
        return None
