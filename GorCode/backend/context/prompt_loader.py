"""
Custom Prompt Loader
====================

Loads custom prompt files (GORCODE.md, AGENTS.md, CLAUDE.md) with priority support.
Similar to opencode's system.ts custom() function.
"""

from pathlib import Path
from typing import Optional


# Priority order: GORCODE.md > AGENTS.md > CLAUDE.md
CUSTOM_PROMPT_FILES = [
    "GORCODE.md",
    "AGENTS.md", 
    "CLAUDE.md",
]


def load_custom_prompt(project_path: str) -> Optional[str]:
    """
    Load custom prompt file from project root directory.
    
    Searches for prompt files in priority order:
    1. GORCODE.md (highest priority)
    2. AGENTS.md
    3. CLAUDE.md
    
    Returns the content of the first found file and stops searching.
    
    Args:
        project_path: Project root directory path
        
    Returns:
        Content of the custom prompt file, or None if no file found
        
    Example:
        >>> prompt = load_custom_prompt("/path/to/project")
        >>> if prompt:
        ...     print(f"Loaded custom prompt: {len(prompt)} chars")
    """
    if not project_path:
        return None
    
    project_root = Path(project_path)
    if not project_root.exists():
        return None
    
    # Search in priority order, stop at first match
    for prompt_file_name in CUSTOM_PROMPT_FILES:
        prompt_file = project_root / prompt_file_name
        
        if prompt_file.exists() and prompt_file.is_file():
            try:
                content = prompt_file.read_text(encoding="utf-8")
                if content.strip():
                    # Found valid prompt file - return immediately
                    return content.strip()
            except (OSError, UnicodeDecodeError) as e:
                # Log error but continue searching
                print(f"[PromptLoader] Warning: Failed to read {prompt_file}: {e}")
                continue
    
    # No custom prompt file found
    return None


def get_custom_prompt_file_path(project_path: str) -> Optional[Path]:
    """
    Get the path of the custom prompt file that would be loaded.
    
    Useful for determining which file exists or would be created.
    
    Args:
        project_path: Project root directory path
        
    Returns:
        Path to the first existing custom prompt file, or None if none found
    """
    if not project_path:
        return None
    
    project_root = Path(project_path)
    if not project_root.exists():
        return None
    
    for prompt_file_name in CUSTOM_PROMPT_FILES:
        prompt_file = project_root / prompt_file_name
        if prompt_file.exists() and prompt_file.is_file():
            return prompt_file
    
    return None


def get_default_prompt_file_path(project_path: str) -> Path:
    """
    Get the default path for creating a new custom prompt file.
    
    Always returns GORCODE.md path (highest priority).
    
    Args:
        project_path: Project root directory path
        
    Returns:
        Path to GORCODE.md in project root
    """
    project_root = Path(project_path)
    return project_root / CUSTOM_PROMPT_FILES[0]  # GORCODE.md
