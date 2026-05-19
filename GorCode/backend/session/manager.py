"""
Session Manager
===============

Manages session lifecycle and coordinates with backend executor.
"""

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional
import threading

from .models import Session, SessionSearchResult
from .storage import SessionStorage
from .scope import SCOPE_ALL, SCOPE_PROJECT, normalize_project_path
from ..core.events import EventBus, Event, EventType
from ..context.token_usage import empty_token_usage_dict, normalize_usage_payload


class SessionCloneError(RuntimeError):
    """Raised when a history session cannot be cloned safely."""


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
        self.project_path = normalize_project_path(project_path)
        
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

    def clone_session_for_current_project(
        self,
        source_session: Session,
        source: Dict[str, str],
        agent: str,
        model: str,
    ) -> Session:
        """Clone a loaded history session into a fresh current-project session."""
        self._save_current_before_load()
        self._validate_source_messages(source_session.messages)
        clone = self._build_session_clone(source_session, source, agent, model)
        self._current_session = clone
        self._message_count_since_save = 0
        if not self.storage.save(clone):
            raise SessionCloneError("Failed to save cloned session")
        self.event_bus.emit(EventType.SESSION_LOAD, {
            "session_id": clone.session_id,
            "source_session_id": source.get("session_id", ""),
            "message_count": len(clone.messages),
        })
        self._start_autosave_timer()
        return clone

    def _save_current_before_load(self) -> None:
        if self._current_session and not self.save_current_session():
            raise SessionCloneError("Failed to save current session before loading history")

    def _validate_source_messages(self, messages: Any) -> None:
        if not isinstance(messages, list):
            raise SessionCloneError("Session messages must be a list")
        for index, message in enumerate(messages):
            self._validate_source_message(index, message)

    def _validate_source_message(self, index: int, message: Any) -> None:
        if not isinstance(message, dict):
            raise SessionCloneError(f"Invalid message at index {index}: expected object")
        if "role" not in message:
            raise SessionCloneError(f"Invalid message at index {index}: missing role")
        if "content" not in message:
            raise SessionCloneError(f"Invalid message at index {index}: missing content")

    def _build_session_clone(
        self,
        source_session: Session,
        source: Dict[str, str],
        agent: str,
        model: str,
    ) -> Session:
        now = datetime.now()
        clone = Session.create_new(
            agent=agent,
            model=model,
            project_path=self.project_path,
            title=source_session.title,
        )
        clone.messages = deepcopy(source_session.messages)
        clone.metadata.created_at = now
        clone.metadata.updated_at = now
        clone.metadata.message_count = len(clone.messages)
        clone.metadata.token_usage = empty_token_usage_dict()
        self._set_clone_source_metadata(clone, source_session, source)
        return clone

    def _set_clone_source_metadata(
        self,
        clone: Session,
        source_session: Session,
        source: Dict[str, str],
    ) -> None:
        clone.metadata.source_kind = source.get("kind", "")
        clone.metadata.source_session_id = source.get("session_id", "")
        clone.metadata.source_path = source.get("path", "")
        clone.metadata.source_agent = source_session.metadata.agent
        clone.metadata.source_model = source_session.metadata.model
    
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

    def set_token_usage(self, usage: Dict[str, Any]) -> None:
        """Set real provider token usage metadata for the current session."""
        if self._current_session:
            self._current_session.metadata.token_usage = normalize_usage_payload(usage)
            self._current_session.metadata.updated_at = datetime.now()

    def clear_token_usage(self) -> None:
        """Clear real provider token usage metadata for the current session."""
        if self._current_session:
            self._current_session.metadata.token_usage = empty_token_usage_dict()
            self._current_session.metadata.updated_at = datetime.now()
    
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
        scope: str = SCOPE_PROJECT,
    ) -> List[SessionSearchResult]:
        """
        List recent sessions.
        
        Args:
            limit: Maximum results
            offset: Pagination offset
            sort_by: Sort field
            scope: project for current-project history, all for global history
            
        Returns:
            List of session search results
        """
        return self.storage.list_sessions(
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            scope=scope,
            project_path=self.project_path,
        )
    
    def search_sessions(
        self,
        query: str,
        limit: int = 10,
        scope: str = SCOPE_PROJECT,
    ) -> List[SessionSearchResult]:
        """
        Search sessions.
        
        Args:
            query: Search query
            limit: Maximum results
            scope: project for current-project history, all for global history
            
        Returns:
            List of matching sessions
        """
        return self.storage.search(query, limit, scope=scope, project_path=self.project_path)
    
    def delete_session(self, session_id: str, scope: str = SCOPE_PROJECT) -> bool:
        """
        Delete a session.
        
        Args:
            session_id: Session ID to delete
            scope: project for current-project history, all for global history
            
        Returns:
            True if successful
        """
        # Don't delete current session
        if self._current_session and self._current_session.session_id == session_id:
            return False
        
        if not self.storage.load_scoped(session_id, scope, self.project_path):
            return False
        return self.storage.delete(session_id)
    
    def get_session_count(self, scope: str = SCOPE_ALL) -> int:
        """Get total session count."""
        return self.storage.count(scope=scope, project_path=self.project_path)

    def list_session_ids(self, scope: str = SCOPE_ALL) -> List[str]:
        """List all stored session IDs."""
        return self.storage.list_session_ids(scope=scope, project_path=self.project_path)
    
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
