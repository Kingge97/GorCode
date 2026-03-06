"""
Path Utilities
==============

Utility functions for path handling.
"""

import os
from pathlib import Path
from typing import Optional


def get_user_config_dir() -> Path:
    """
    Get user configuration directory.
    
    Returns:
        Path to user configuration directory (~/.gorcode)
    """
    return Path.home() / ".gorcode"


def get_project_config_dir(project_path: str = None) -> Path:
    """
    Get project configuration directory.
    
    Args:
        project_path: Path to project directory, defaults to current directory
        
    Returns:
        Path to project configuration directory
    """
    base_path = Path(project_path) if project_path else Path.cwd()
    return base_path / ".gorcode"


def get_default_project_path() -> Path:
    """
    Get default project path (current working directory).
    
    Returns:
        Path to current working directory
    """
    return Path.cwd()


def ensure_dir(path: Path) -> Path:
    """
    Ensure a directory exists, creating it if necessary.
    
    Args:
        path: Path to directory
        
    Returns:
        The path (for chaining)
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_path(base: Path, target: str) -> Optional[Path]:
    """
    Safely resolve a path relative to a base directory.
    
    Ensures the resolved path is within the base directory.
    
    Args:
        base: Base directory
        target: Target path (relative or absolute)
        
    Returns:
        Resolved path if safe, None otherwise
    """
    try:
        base = base.resolve()
        target_path = (base / target).resolve()
        
        # Check if target is within base
        if str(target_path).startswith(str(base)):
            return target_path
        return None
    except Exception:
        return None


def is_valid_project_path(path: Path) -> bool:
    """
    Check if a path is a valid project directory.
    
    Args:
        path: Path to check
        
    Returns:
        True if path is a valid project directory
    """
    return path.exists() and path.is_dir()
