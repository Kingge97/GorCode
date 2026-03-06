"""
Session Storage
===============

Handles session persistence to disk.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import threading
import shutil

from .models import Session, SessionMetadata, SessionSearchResult


class SessionStorage:
    """
    Handles session persistence.
    
    Sessions are stored as JSON files in a dedicated directory.
    Directory structure:
        ~/.gorcode/
            sessions/
                {session_id}.json
                index.json  # Session index for fast listing
    """
    
    SESSIONS_DIR = "sessions"
    INDEX_FILE = "index.json"
    SESSION_EXTENSION = ".json"
    
    def __init__(self, base_path: str = None):
        """
        Initialize session storage.
        
        Args:
            base_path: Base path for storage (defaults to ~/.gorcode)
        """
        if base_path:
            self.base_path = Path(base_path)
        else:
            self.base_path = Path.home() / ".gorcode"
        
        self.sessions_path = self.base_path / self.SESSIONS_DIR
        self.index_path = self.sessions_path / self.INDEX_FILE
        self._lock = threading.Lock()
        
        # Ensure directory exists
        self._ensure_directories()
    
    def _ensure_directories(self) -> None:
        """Ensure required directories exist."""
        self.sessions_path.mkdir(parents=True, exist_ok=True)
    
    def _get_session_path(self, session_id: str) -> Path:
        """Get path for a session file."""
        return self.sessions_path / f"{session_id}{self.SESSION_EXTENSION}"
    
    # ========================
    # Index Management
    # ========================
    
    def _load_index(self) -> Dict[str, Dict[str, Any]]:
        """
        Load session index.
        
        Returns:
            Dictionary mapping session_id to metadata
        """
        if self.index_path.exists():
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}
    
    def _save_index(self, index: Dict[str, Dict[str, Any]]) -> None:
        """
        Save session index.
        
        Args:
            index: Index dictionary
        """
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)
    
    def _update_index_entry(self, session: Session) -> None:
        """
        Update index entry for a session.
        
        Args:
            session: Session to update
        """
        with self._lock:
            index = self._load_index()
            index[session.session_id] = {
                "title": session.title or session.generate_title(),
                "created_at": session.metadata.created_at.isoformat(),
                "updated_at": session.metadata.updated_at.isoformat(),
                "message_count": session.metadata.message_count,
                "agent": session.metadata.agent,
            }
            self._save_index(index)
    
    def _remove_index_entry(self, session_id: str) -> None:
        """
        Remove index entry for a session.
        
        Args:
            session_id: Session ID to remove
        """
        with self._lock:
            index = self._load_index()
            if session_id in index:
                del index[session_id]
                self._save_index(index)
    
    # ========================
    # Session CRUD Operations
    # ========================
    
    def save(self, session: Session) -> bool:
        """
        Save a session to disk.
        
        Args:
            session: Session to save
            
        Returns:
            True if successful
        """
        try:
            session_path = self._get_session_path(session.session_id)
            
            with open(session_path, "w", encoding="utf-8") as f:
                json.dump(session.to_dict(), f, indent=2, ensure_ascii=False)
            
            # Update index
            self._update_index_entry(session)
            
            return True
        except IOError as e:
            print(f"Error saving session: {e}")
            return False
    
    def load(self, session_id: str) -> Optional[Session]:
        """
        Load a session from disk.
        
        Args:
            session_id: Session ID to load
            
        Returns:
            Session or None if not found
        """
        session_path = self._get_session_path(session_id)
        
        if not session_path.exists():
            return None
        
        try:
            with open(session_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Session.from_dict(data)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading session {session_id}: {e}")
            return None
    
    def delete(self, session_id: str) -> bool:
        """
        Delete a session.
        
        Args:
            session_id: Session ID to delete
            
        Returns:
            True if successful
        """
        session_path = self._get_session_path(session_id)
        
        try:
            if session_path.exists():
                session_path.unlink()
            self._remove_index_entry(session_id)
            return True
        except IOError as e:
            print(f"Error deleting session {session_id}: {e}")
            return False
    
    def exists(self, session_id: str) -> bool:
        """
        Check if a session exists.
        
        Args:
            session_id: Session ID to check
            
        Returns:
            True if session exists
        """
        return self._get_session_path(session_id).exists()
    
    # ========================
    # Listing and Search
    # ========================
    
    def list_sessions(
        self,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "updated_at",
        ascending: bool = False,
    ) -> List[SessionSearchResult]:
        """
        List sessions with pagination.
        
        Args:
            limit: Maximum number of sessions to return
            offset: Offset for pagination
            sort_by: Field to sort by (updated_at, created_at, title)
            ascending: Sort ascending if True
            
        Returns:
            List of session search results
        """
        index = self._load_index()
        
        # Convert to list and sort
        sessions = []
        for session_id, meta in index.items():
            sessions.append(SessionSearchResult(
                session_id=session_id,
                title=meta.get("title", ""),
                created_at=datetime.fromisoformat(meta["created_at"]),
                updated_at=datetime.fromisoformat(meta["updated_at"]),
                message_count=meta.get("message_count", 0),
                agent=meta.get("agent", "build"),
            ))
        
        # Sort
        reverse = not ascending
        if sort_by == "created_at":
            sessions.sort(key=lambda s: s.created_at, reverse=reverse)
        elif sort_by == "title":
            sessions.sort(key=lambda s: s.title.lower(), reverse=reverse)
        else:  # updated_at (default)
            sessions.sort(key=lambda s: s.updated_at, reverse=reverse)
        
        # Paginate
        return sessions[offset:offset + limit]
    
    def search(
        self,
        query: str,
        limit: int = 10,
    ) -> List[SessionSearchResult]:
        """
        Search sessions by title or content.
        
        Args:
            query: Search query
            limit: Maximum results to return
            
        Returns:
            List of matching sessions
        """
        query = query.lower()
        results = []
        
        index = self._load_index()
        
        for session_id, meta in index.items():
            title = meta.get("title", "").lower()
            
            # Search in title
            if query in title:
                results.append(SessionSearchResult(
                    session_id=session_id,
                    title=meta.get("title", ""),
                    created_at=datetime.fromisoformat(meta["created_at"]),
                    updated_at=datetime.fromisoformat(meta["updated_at"]),
                    message_count=meta.get("message_count", 0),
                    agent=meta.get("agent", "build"),
                ))
                continue
            
            # Search in content (load full session)
            session = self.load(session_id)
            if session:
                for msg in session.messages:
                    content = msg.get("content", "")
                    if isinstance(content, str) and query in content.lower():
                        # Create result with preview
                        preview = content[:100] + "..." if len(content) > 100 else content
                        results.append(SessionSearchResult(
                            session_id=session_id,
                            title=meta.get("title", ""),
                            created_at=datetime.fromisoformat(meta["created_at"]),
                            updated_at=datetime.fromisoformat(meta["updated_at"]),
                            message_count=meta.get("message_count", 0),
                            agent=meta.get("agent", "build"),
                            preview=preview,
                        ))
                        break
            
            if len(results) >= limit:
                break
        
        return results[:limit]
    
    def count(self) -> int:
        """
        Get total session count.
        
        Returns:
            Number of sessions
        """
        return len(self._load_index())
    
    # ========================
    # Maintenance
    # ========================
    
    def rebuild_index(self) -> int:
        """
        Rebuild index from session files.
        
        Returns:
            Number of sessions indexed
        """
        index = {}
        count = 0
        
        for session_file in self.sessions_path.glob(f"*{self.SESSION_EXTENSION}"):
            if session_file.name == self.INDEX_FILE:
                continue
            
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                session = Session.from_dict(data)
                index[session.session_id] = {
                    "title": session.title or session.generate_title(),
                    "created_at": session.metadata.created_at.isoformat(),
                    "updated_at": session.metadata.updated_at.isoformat(),
                    "message_count": session.metadata.message_count,
                    "agent": session.metadata.agent,
                }
                count += 1
            except (json.JSONDecodeError, IOError, KeyError) as e:
                print(f"Error indexing {session_file}: {e}")
        
        self._save_index(index)
        return count
    
    def cleanup_old_sessions(self, days: int = 30) -> int:
        """
        Remove sessions older than specified days.
        
        Args:
            days: Number of days (sessions older than this are removed)
            
        Returns:
            Number of sessions removed
        """
        cutoff = datetime.now().timestamp() - (days * 24 * 60 * 60)
        removed = 0
        
        index = self._load_index()
        for session_id, meta in list(index.items()):
            updated_at = datetime.fromisoformat(meta["updated_at"])
            if updated_at.timestamp() < cutoff:
                if self.delete(session_id):
                    removed += 1
        
        return removed
    
    def get_storage_info(self) -> Dict[str, Any]:
        """
        Get storage information.
        
        Returns:
            Dictionary with storage stats
        """
        total_size = 0
        file_count = 0
        
        for session_file in self.sessions_path.glob(f"*{self.SESSION_EXTENSION}"):
            if session_file.name == self.INDEX_FILE:
                continue
            total_size += session_file.stat().st_size
            file_count += 1
        
        return {
            "sessions_path": str(self.sessions_path),
            "session_count": file_count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
        }
