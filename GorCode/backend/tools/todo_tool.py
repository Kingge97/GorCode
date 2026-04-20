"""
Todo Tool
=========

Tool for managing todo lists to track multi-step task progress.

Based on the v4_skills_agent.py implementation, this provides a simple
in-memory task tracking system that helps the model organize complex work.
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from .core_tool_support.base import BaseTool, ToolResult
from .core_tool_support.tool_utils import build_parameters_schema, tool_error_result


@dataclass
class TodoItem:
    """Single todo item."""
    
    content: str
    status: str  # pending, in_progress, completed
    active_form: str
    
    def __post_init__(self):
        """Validate status after creation."""
        valid_statuses = ("pending", "in_progress", "completed")
        if self.status not in valid_statuses:
            raise ValueError(f"Invalid status '{self.status}'. Must be one of: {valid_statuses}")


class TodoManager:
    """
    Task list manager with constraints.
    
    Constraints:
    - Maximum 20 items
    - Only one item can be 'in_progress' at a time
    """
    
    MAX_ITEMS = 20
    
    def __init__(self):
        self.items: List[TodoItem] = []
    
    def update(self, items: List[Dict[str, Any]]) -> str:
        """
        Update the todo list with new items.
        
        Args:
            items: List of item dicts with 'content', 'status', 'activeForm' keys
            
        Returns:
            Rendered string representation of the updated list
            
        Raises:
            ValueError: If validation fails
        """
        validated = []
        in_progress_count = 0
        
        for i, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            active_form = str(item.get("activeForm", "")).strip()
            
            # Validation: content always required
            # activeForm required only for non-completed tasks
            if not content:
                raise ValueError(f"Item {i}: 'content' is required")
            if status != "completed" and not active_form:
                raise ValueError(f"Item {i}: 'activeForm' is required for non-completed tasks")
            
            valid_statuses = ("pending", "in_progress", "completed")
            if status not in valid_statuses:
                raise ValueError(f"Item {i}: invalid status '{status}'. Must be one of: {valid_statuses}")
            
            if status == "in_progress":
                in_progress_count += 1
            
            validated.append(TodoItem(
                content=content,
                status=status,
                active_form=active_form
            ))
        
        # Constraint: only one in_progress
        if in_progress_count > 1:
            raise ValueError("Only one task can be 'in_progress' at a time")
        
        # Constraint: max items
        if len(validated) > self.MAX_ITEMS:
            raise ValueError(f"Maximum {self.MAX_ITEMS} tasks allowed")
        
        self.items = validated
        return self.render()
    
    def render(self) -> str:
        """Render the todo list as a readable string."""
        if not self.items:
            return "No todos."
        
        lines = []
        for item in self.items:
            if item.status == "completed":
                mark = "[x]"
            elif item.status == "in_progress":
                mark = "[>]"
            else:
                mark = "[ ]"
            lines.append(f"{mark} {item.content}")
        
        done = sum(1 for item in self.items if item.status == "completed")
        total = len(self.items)
        
        return "\n".join(lines) + f"\n({done}/{total} done)"
    
    def clear(self) -> None:
        """Clear all items."""
        self.items = []
    
    def get_items(self) -> List[TodoItem]:
        """Get a copy of all items."""
        return self.items.copy()


class TodoTool(BaseTool):
    """
    Tool for managing todo lists.
    
    This tool allows the model to track multi-step work progress.
    It maintains state across calls within the same session.
    
    Usage:
        - Initialize: Call with a list of tasks at the start of complex work
        - Update: Call again to update statuses as work progresses
        - Complete: All tasks marked 'completed' when done
    
    Constraints:
        - Maximum 20 tasks
        - Only one task can be 'in_progress' at a time
    """
    
    name = "TodoWrite"
    description = "Update the task list to track multi-step work progress"
    category = "task"
    needs_encoding = False
    
    # Class-level manager for session-wide persistence (Scheme A)
    _manager: Optional[TodoManager] = None
    
    def __init__(self, default_encoding: str = "utf-8"):
        """Initialize the todo tool."""
        super().__init__(default_encoding)
        # Initialize class-level manager if not exists
        if TodoTool._manager is None:
            TodoTool._manager = TodoManager()
    
    def execute(
        self,
        items: List[Dict[str, Any]],
    ) -> ToolResult:
        """
        Execute the todo update.
        
        Args:
            items: List of task items, each with:
                - content: Task description
                - status: One of 'pending', 'in_progress', 'completed'
                - activeForm: Active form description for LLM context
                
        Returns:
            ToolResult with rendered todo list
        """
        try:
            result = TodoTool._manager.update(items)
            
            # Calculate progress metadata
            total = len(TodoTool._manager.items)
            completed = sum(1 for item in TodoTool._manager.items if item.status == "completed")
            in_progress = sum(1 for item in TodoTool._manager.items if item.status == "in_progress")
            
            return ToolResult(
                success=True,
                output=result,
                metadata={
                    "total": total,
                    "completed": completed,
                    "in_progress": in_progress,
                    "pending": total - completed - in_progress,
                }
            )
        except ValueError as e:
            return tool_error_result(
                e,
                output=TodoTool._manager.render() if TodoTool._manager.items else "No todos.",
            )
        except Exception as e:
            return tool_error_result(e, prefix="Todo update failed: ")
    
    def get_description(self) -> str:
        """Get tool description for model API."""
        return """Update the task list to track multi-step work progress.

Use this tool when:
1. Starting a complex multi-step task - initialize the todo list
2. Progressing through work - update task statuses
3. Completing steps - mark tasks as 'completed'

Task statuses:
- pending: Task not yet started
- in_progress: Currently working on this task (only one allowed)
- completed: Task finished

Constraints:
- Maximum 20 tasks
- Only one task can be 'in_progress' at a time

Example:
[
  {"content": "Read configuration files", "status": "completed", "activeForm": "Reading config"},
  {"content": "Implement feature X", "status": "in_progress", "activeForm": "Implementing feature X"},
  {"content": "Write tests", "status": "pending", "activeForm": "Writing tests"}
]"""

    def get_parameters(self) -> Dict[str, Any]:
        """Get tool parameter schema."""
        return build_parameters_schema(
            properties={
                "items": {
                    "type": "array",
                    "description": "List of tasks to track",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Task description"
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                                "description": "Task status"
                            },
                            "activeForm": {
                                "type": "string",
                                "description": "Active form description for LLM context"
                            }
                        },
                        "required": ["content", "status", "activeForm"]
                    }
                }
            },
            required=["items"],
        )
    
    @classmethod
    def clear(cls) -> None:
        """Clear the todo list. Useful for testing or session reset."""
        if cls._manager is not None:
            cls._manager.clear()
    
    @classmethod
    def get_manager(cls) -> Optional[TodoManager]:
        """Get the current manager instance."""
        return cls._manager
