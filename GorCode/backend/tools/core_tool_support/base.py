"""
Tool Base Classes
=================

Base classes and registry for tools.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
import json

from .tool_utils import tool_error_result
from ...utils.serialization import dataclass_to_dict


@dataclass
class ToolResult:
    """Result of a tool execution."""
    
    success: bool
    output: str
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __str__(self) -> str:
        if self.success:
            return self.output
        return f"Error: {self.error}"


@dataclass
class ToolDefinition:
    """Definition of a tool for model API."""
    
    name: str
    description: str
    parameters: Dict[str, Any]
    category: str = "general"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to OpenAI tool format."""
        return dataclass_to_dict(self, exclude_fields={"category"})


class BaseTool(ABC):
    """
    Abstract base class for all tools.
    
    All tools must inherit from this class and implement the execute method.
    """
    
    # Tool metadata
    name: str = "base_tool"
    description: str = "Base tool class"
    category: str = "general"
    
    # Whether this tool needs encoding parameter
    needs_encoding: bool = False
    
    # Whether this tool requires permission check
    requires_permission: bool = False
    
    def __init__(self, default_encoding: str = "utf-8"):
        """
        Initialize tool.
        
        Args:
            default_encoding: Default encoding for file operations
        """
        self.default_encoding = default_encoding
        self._permission_callback = None
    
    def set_permission_callback(self, callback):
        """
        Set permission check callback.
        
        Args:
            callback: Async function(permission_type, metadata) -> PermissionResponse
        """
        self._permission_callback = callback
    
    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """
        Execute the tool.
        
        Args:
            **kwargs: Tool arguments
            
        Returns:
            ToolResult object with execution result
        """
        pass
    
    @abstractmethod
    def get_parameters(self) -> Dict[str, Any]:
        """
        Get tool parameter schema for model API.
        
        Returns:
            JSON schema dict for tool parameters
        """
        pass

    def get_description(self) -> str:
        """
        Get tool description for model API.
        
        Returns:
            Description string
        """
        return self.description

    def get_definition(self) -> ToolDefinition:
        """
        Get tool definition for model API.
        
        Returns:
            ToolDefinition object
        """
        return ToolDefinition(
            name=self.name,
            description=self.get_description(),
            parameters=self.get_parameters(),
            category=self.category,
        )
    
    def validate_args(self, **kwargs) -> bool:
        """
        Validate tool arguments.
        
        Args:
            **kwargs: Tool arguments
            
        Returns:
            True if arguments are valid
        """
        return True
    
    def to_model_tool(self) -> Dict[str, Any]:
        """
        Convert tool to model-compatible format.
        
        Returns:
            Dictionary in OpenAI tool format
        """
        definition = self.get_definition()
        return {
            "type": "function",
            "function": definition.to_dict(),
        }


class ToolRegistry:
    """
    Registry for managing available tools.
    
    Tools are organized by category and can be retrieved by name or category.
    """
    
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._categories: Dict[str, List[str]] = {}
    
    def register(self, tool: BaseTool) -> None:
        """
        Register a tool.
        
        Args:
            tool: Tool instance to register
        """
        self._tools[tool.name] = tool
        
        # Add to category
        if tool.category not in self._categories:
            self._categories[tool.category] = []
        self._categories[tool.category].append(tool.name)
    
    def unregister(self, tool_name: str) -> bool:
        """
        Unregister a tool.
        
        Args:
            tool_name: Name of tool to unregister
            
        Returns:
            True if tool was unregistered, False if not found
        """
        if tool_name in self._tools:
            tool = self._tools[tool_name]
            # Remove from category
            if tool.category in self._categories:
                self._categories[tool.category] = [
                    name for name in self._categories[tool.category]
                    if name != tool_name
                ]
            del self._tools[tool_name]
            return True
        return False
    
    def get(self, tool_name: str) -> Optional[BaseTool]:
        """
        Get a tool by name.
        
        Args:
            tool_name: Name of tool to get
            
        Returns:
            Tool instance or None if not found
        """
        return self._tools.get(tool_name)
    
    def get_by_category(self, category: str) -> List[BaseTool]:
        """
        Get all tools in a category.
        
        Args:
            category: Category name
            
        Returns:
            List of tools in the category
        """
        if category not in self._categories:
            return []
        return [self._tools[name] for name in self._categories[category]]
    
    def get_all_tools(self) -> List[BaseTool]:
        """
        Get all registered tools.
        
        Returns:
            List of all tools
        """
        return list(self._tools.values())
    
    def get_tool_definitions(self, category: str = None) -> List[Dict[str, Any]]:
        """
        Get tool definitions for model API.
        
        Args:
            category: Optional category filter
            
        Returns:
            List of tool definitions in simplified format (for GorAI_LLMClient compatibility)
        """
        if category:
            tools = self.get_by_category(category)
        else:
            tools = self.get_all_tools()
        # 返回简化格式，不使用 OpenAI 格式的嵌套结构
        return [tool.get_definition().to_dict() for tool in tools]
    
    def get_categories(self) -> List[str]:
        """
        Get all tool categories.
        
        Returns:
            List of category names
        """
        return list(self._categories.keys())
    
    def execute(self, tool_name: str, **kwargs) -> ToolResult:
        """
        Execute a tool by name.
        
        Args:
            tool_name: Name of tool to execute
            **kwargs: Tool arguments
            
        Returns:
            ToolResult from execution
        """
        tool = self.get(tool_name)
        if tool is None:
            return ToolResult(
                success=False,
                output="",
                error=f"Tool '{tool_name}' not found"
            )
        
        try:
            # Add encoding parameter for tools that need it
            if tool.needs_encoding and "encoding" not in kwargs:
                kwargs["encoding"] = tool.default_encoding
            
            return tool.execute(**kwargs)
        except Exception as e:
            return tool_error_result(e)
    
    @property
    def tools(self) -> Dict[str, BaseTool]:
        """Get all tools as dictionary."""
        return self._tools.copy()
