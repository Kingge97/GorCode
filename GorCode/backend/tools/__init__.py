"""
Tools Module
============

Tool implementations for the agent system.
"""

from .core_tool_support.base import BaseTool, ToolRegistry, ToolResult, ToolDefinition
from .file_read_tool import ReadTool
from .file_write_tool import WriteTool
from .file_edit_tool import EditTool
from .file_ls_tool import LSTool
from .file_tool_support.file_state import FileStateCache
from .file_tool_support.file_settings import FileToolSettings
from ..lsp import LspManager
from .search_tool import GlobTool, GrepTool, BashTool
from .task_tool import TaskTool, SubagentResult
from .todo_tool import TodoTool, TodoManager, TodoItem
from .skill_tool import SkillTool


def initialize_tools(default_encoding: str = "utf-8", config=None) -> ToolRegistry:
    """
    Initialize and register all available tools.
    
    Args:
        default_encoding: Default encoding for file operations
        
    Returns:
        ToolRegistry with all tools registered
    """
    registry = ToolRegistry()
    
    file_settings = FileToolSettings.from_config(config)
    file_state_cache = FileStateCache()
    lsp_manager = LspManager()

    # File tools
    registry.register(
        ReadTool(
            default_encoding=default_encoding,
            file_state_cache=file_state_cache,
            settings=file_settings,
        )
    )
    registry.register(
        WriteTool(
            default_encoding=default_encoding,
            file_state_cache=file_state_cache,
            settings=file_settings,
            lsp_manager=lsp_manager,
        )
    )
    registry.register(
        EditTool(
            default_encoding=default_encoding,
            file_state_cache=file_state_cache,
            settings=file_settings,
            lsp_manager=lsp_manager,
        )
    )
    registry.register(LSTool(default_encoding=default_encoding))
    
    # Search tools
    registry.register(GlobTool(default_encoding=default_encoding))
    registry.register(GrepTool(default_encoding=default_encoding))
    registry.register(BashTool(default_encoding=default_encoding))
    
    # Task tool (placeholder, needs model_connector set later)
    registry.register(TaskTool(default_encoding=default_encoding))
    
    # Todo tool for tracking multi-step work
    registry.register(TodoTool(default_encoding=default_encoding))
    
    # Skill tool for loading specialized knowledge
    registry.register(SkillTool(default_encoding=default_encoding))
    
    return registry


__all__ = [
    "BaseTool",
    "ToolRegistry",
    "ToolResult",
    "ToolDefinition",
    "ReadTool",
    "WriteTool",
    "EditTool",
    "LSTool",
    "GlobTool",
    "GrepTool",
    "BashTool",
    "TaskTool",
    "SubagentResult",
    "TodoTool",
    "TodoManager",
    "TodoItem",
    "SkillTool",
    "initialize_tools",
]
