"""
Tools Module
============

Tool implementations for the agent system.
"""

from .base import BaseTool, ToolRegistry, ToolResult, ToolDefinition
from .file_tools import ReadTool, WriteTool, EditTool, LSTool
from .search_tools import GlobTool, GrepTool, BashTool
from .task_tool import TaskTool, SubagentResult
from .todo_tool import TodoTool, TodoManager, TodoItem
from .skill_tool import SkillTool


def initialize_tools(default_encoding: str = "utf-8") -> ToolRegistry:
    """
    Initialize and register all available tools.
    
    Args:
        default_encoding: Default encoding for file operations
        
    Returns:
        ToolRegistry with all tools registered
    """
    registry = ToolRegistry()
    
    # File tools
    registry.register(ReadTool(default_encoding=default_encoding))
    registry.register(WriteTool(default_encoding=default_encoding))
    registry.register(EditTool(default_encoding=default_encoding))
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
