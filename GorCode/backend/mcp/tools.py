"""
MCP Tool Wrapper
================

Wraps MCP tools as GorCode tools.
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from ..tools.base import BaseTool, ToolResult, ToolDefinition
from .manager import MCPManager, MCPTool, MCPConnectionStatus


class MCPToolWrapper(BaseTool):
    """Wrapper for MCP tools to be used in GorCode."""
    
    name = "mcp_tool"
    description = "Call a tool from an MCP server"
    category = "mcp"
    needs_encoding = False
    
    def __init__(
        self,
        mcp_manager: MCPManager,
        default_encoding: str = "utf-8",
    ):
        super().__init__(default_encoding=default_encoding)
        self.mcp_manager = mcp_manager
    
    def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any] = None,
        server_name: str = None,
    ) -> ToolResult:
        """
        Execute an MCP tool.
        
        Args:
            tool_name: Name of the MCP tool to call
            arguments: Arguments to pass to the tool
            server_name: Optional server name (auto-detected if not provided)
            
        Returns:
            ToolResult with the tool output
        """
        import asyncio
        
        arguments = arguments or {}
        
        try:
            # Run async call in sync context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    self.mcp_manager.call_tool(tool_name, arguments)
                )
            finally:
                loop.close()
            
            # Format result
            if isinstance(result, dict):
                output = result.get("content", str(result))
            else:
                output = str(result)
            
            return ToolResult(
                success=True,
                output=output,
                metadata={"server": server_name or "auto"},
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
    
    def get_definition(self) -> ToolDefinition:
        """Get tool definition for model API."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters={
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Name of the MCP tool to call",
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments to pass to the tool",
                    },
                    "server_name": {
                        "type": "string",
                        "description": "Optional server name",
                    },
                },
                "required": ["tool_name"],
            },
            category=self.category,
        )


def create_mcp_tools(mcp_manager: MCPManager) -> List[BaseTool]:
    """
    Create tool wrappers for all connected MCP tools.
    
    Args:
        mcp_manager: MCP manager instance
        
    Returns:
        List of tool wrappers
    """
    tools = []
    
    # Add the generic MCP tool wrapper
    tools.append(MCPToolWrapper(mcp_manager))
    
    # Add individual tool wrappers for each MCP tool
    for mcp_tool in mcp_manager.get_all_tools():
        wrapper = MCPIndividualToolWrapper(mcp_tool, mcp_manager)
        tools.append(wrapper)
    
    return tools


class MCPIndividualToolWrapper(BaseTool):
    """Wrapper for individual MCP tools."""
    
    category = "mcp"
    needs_encoding = False
    
    def __init__(
        self,
        mcp_tool: MCPTool,
        mcp_manager: MCPManager,
        default_encoding: str = "utf-8",
    ):
        super().__init__(default_encoding=default_encoding)
        self.mcp_tool = mcp_tool
        self.mcp_manager = mcp_manager
        self.name = f"mcp_{mcp_tool.server_name}_{mcp_tool.name}"
        self.description = f"[MCP:{mcp_tool.server_name}] {mcp_tool.description}"
    
    def execute(self, **kwargs) -> ToolResult:
        """Execute the MCP tool."""
        import asyncio
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    self.mcp_manager.call_tool(self.mcp_tool.name, kwargs)
                )
            finally:
                loop.close()
            
            if isinstance(result, dict):
                output = result.get("content", str(result))
            else:
                output = str(result)
            
            return ToolResult(
                success=True,
                output=output,
                metadata={"server": self.mcp_tool.server_name},
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
    
    def get_definition(self) -> ToolDefinition:
        """Get tool definition."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.mcp_tool.input_schema,
            category=self.category,
        )
