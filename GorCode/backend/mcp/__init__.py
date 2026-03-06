"""
MCP Module
==========

Model Context Protocol integration for GorCode.
"""

from .manager import (
    MCPManager,
    MCPConnection,
    StdioMCPConnection,
    MCPServerConfig,
    MCPTool,
    MCPResource,
    MCPConnectionStatus,
)
from .tools import MCPToolWrapper, MCPIndividualToolWrapper, create_mcp_tools

__all__ = [
    "MCPManager",
    "MCPConnection",
    "StdioMCPConnection",
    "MCPServerConfig",
    "MCPTool",
    "MCPResource",
    "MCPConnectionStatus",
    "MCPToolWrapper",
    "MCPIndividualToolWrapper",
    "create_mcp_tools",
]
