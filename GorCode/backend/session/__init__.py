"""
Session Module
==============

Session management for GorCode including persistence, history, and debug logging.
"""

from .models import Session, SessionMetadata, SessionSearchResult
from .storage import SessionStorage
from .manager import SessionCloneError, SessionManager
from .debug_logger import DebugLogger
from .scope import normalize_project_path, paths_match

__all__ = [
    "Session",
    "SessionMetadata",
    "SessionSearchResult",
    "SessionStorage",
    "SessionManager",
    "SessionCloneError",
    "DebugLogger",
    "normalize_project_path",
    "paths_match",
]
