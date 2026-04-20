"""
MCP Tool Wrapper
================

Wraps MCP tools as GorCode tools.
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from ..tools.core_tool_support.base import BaseTool, ToolResult
from ..tools.core_tool_support.tool_utils import tool_error_result
from .manager import MCPManager, MCPTool, MCPConnectionStatus


def _call_mcp_tool_sync(mcp_manager: MCPManager, tool_name: str, arguments: Dict[str, Any]) -> Any:
    """
    Run an async MCP tool call in a sync context.
    """
    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(mcp_manager.call_tool(tool_name, arguments))
    finally:
        loop.close()


def _format_mcp_output(result: Any) -> str:
    """
    Normalize MCP tool output into a string.
    """
    if isinstance(result, dict):
        return result.get("content", str(result))
    return str(result)


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
        arguments = arguments or {}
        
        try:
            # Run async call in sync context
            result = _call_mcp_tool_sync(self.mcp_manager, tool_name, arguments)
            
            # Format result
            output = _format_mcp_output(result)
            
            return ToolResult(
                success=True,
                output=output,
                metadata={"server": server_name or "auto"},
            )
            
        except Exception as e:
            return tool_error_result(e)
    
    def get_parameters(self) -> Dict[str, Any]:
        """Get tool parameter schema."""
        return {
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
        }


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
        try:
            result = _call_mcp_tool_sync(self.mcp_manager, self.mcp_tool.name, kwargs)
            output = _format_mcp_output(result)
            
            return ToolResult(
                success=True,
                output=output,
                metadata={"server": self.mcp_tool.server_name},
            )
            
        except Exception as e:
            return tool_error_result(e)
    
    def get_parameters(self) -> Dict[str, Any]:
        """Get tool parameter schema."""
        return self.mcp_tool.input_schema
