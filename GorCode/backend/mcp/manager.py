"""
MCP (Model Context Protocol) Module
====================================

MCP connection management and tool discovery.
"""

import asyncio
import json
import os
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
import uuid


class MCPConnectionStatus(Enum):
    """MCP connection status."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class MCPServerConfig:
    """MCP server configuration."""
    
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    auto_connect: bool = True
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPServerConfig":
        """Create from dictionary.
        
        Supports both GorCode native format and Claude Code compatible format.
        """
        # Handle Claude Code format: extract stdio config when type is "stdio"
        server_type = data.get("type", "stdio")
        if server_type == "stdio" and "command" in data:
            # Direct stdio configuration (Claude Code compatible)
            command = data.get("command", "")
            args = data.get("args", [])
            env = data.get("env", {})
        elif "command" in data:
            # Native GorCode format
            command = data.get("command", "")
            args = data.get("args", [])
            env = data.get("env", {})
        else:
            command = ""
            args = []
            env = {}
        
        return cls(
            name=data.get("name", "unknown"),
            command=command,
            args=args,
            env=env,
            cwd=data.get("cwd"),
            auto_connect=data.get("auto_connect", True),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "cwd": self.cwd,
            "auto_connect": self.auto_connect,
        }


@dataclass
class MCPTool:
    """MCP tool definition."""
    
    name: str
    description: str
    input_schema: Dict[str, Any]
    server_name: str
    
    def to_openai_tool(self) -> Dict[str, Any]:
        """Convert to OpenAI tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            }
        }


@dataclass
class MCPResource:
    """MCP resource definition."""
    
    uri: str
    name: str
    description: Optional[str] = None
    mime_type: Optional[str] = None
    server_name: str = ""


class MCPConnection(ABC):
    """Abstract base class for MCP connections."""
    
    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.status = MCPConnectionStatus.DISCONNECTED
        self.tools: List[MCPTool] = []
        self.resources: List[MCPResource] = []
        self._error_message: Optional[str] = None
    
    @property
    def name(self) -> str:
        """Get server name."""
        return self.config.name
    
    @property
    def error_message(self) -> Optional[str]:
        """Get last error message."""
        return self._error_message
    
    @abstractmethod
    async def connect(self) -> bool:
        """Connect to MCP server."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """Disconnect from MCP server."""
        pass
    
    @abstractmethod
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool on the MCP server."""
        pass
    
    @abstractmethod
    async def list_tools(self) -> List[MCPTool]:
        """List available tools from the server."""
        pass
    
    @abstractmethod
    async def list_resources(self) -> List[MCPResource]:
        """List available resources from the server."""
        pass


class StdioMCPConnection(MCPConnection):
    """MCP connection using stdio transport."""
    
    def __init__(self, config: MCPServerConfig, encoding: str = "utf-8"):
        super().__init__(config)
        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._encoding = encoding
    
    async def connect(self) -> bool:
        """Connect to MCP server via stdio."""
        self.status = MCPConnectionStatus.CONNECTING
        
        try:
            # Validate config
            if not self.config.command:
                self.status = MCPConnectionStatus.ERROR
                self._error_message = "No command specified in MCP server config"
                return False
            
            # Prepare environment
            env = dict(os.environ)
            env.update(self.config.env)
            
            # Build command
            cmd = [self.config.command] + self.config.args
            
            # On Windows, use shell=True for commands like npx that are .cmd files
            use_shell = False
            if sys.platform == "win32":
                # Check if command is a shell command (npx, npm, etc.)
                shell_commands = ["npx", "npm", "node", "yarn", "pnpm"]
                if self.config.command.lower() in shell_commands:
                    use_shell = True
            
            # Start the process
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    cwd=self.config.cwd,
                    text=False,  # Use binary mode to handle UTF-8 properly
                    bufsize=0,   # Unbuffered for binary mode
                    shell=use_shell,
                )
            except FileNotFoundError as e:
                self.status = MCPConnectionStatus.ERROR
                self._error_message = f"Command not found: {self.config.command}. Make sure it's installed and in PATH."
                return False
            except Exception as e:
                self.status = MCPConnectionStatus.ERROR
                self._error_message = f"Failed to start process: {str(e)}"
                return False
            
            # Initialize the connection
            init_result = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "clientInfo": {
                    "name": "GorCode",
                    "version": "0.1.0"
                },
                "capabilities": {
                    "tools": {},
                    "resources": {}
                }
            })
            
            if init_result and "result" in init_result:
                # Send initialized notification
                await self._send_notification("notifications/initialized", {})
                
                # Discover tools and resources
                self.tools = await self.list_tools()
                self.resources = await self.list_resources()
                
                self.status = MCPConnectionStatus.CONNECTED
                self._error_message = None
                return True
            else:
                # Try to read stderr for more info
                stderr_output = ""
                if self._process and self._process.stderr:
                    try:
                        stderr_output = self._process.stderr.read(1024)
                    except:
                        pass
                
                self.status = MCPConnectionStatus.ERROR
                if stderr_output:
                    self._error_message = f"Failed to initialize MCP connection: {stderr_output[:200]}"
                else:
                    self._error_message = f"Failed to initialize MCP connection: {init_result}"
                return False
                
        except Exception as e:
            self.status = MCPConnectionStatus.ERROR
            self._error_message = f"Connection error: {str(e)}"
            return False
    
    async def disconnect(self) -> bool:
        """Disconnect from MCP server."""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
            finally:
                self._process = None
        
        self.status = MCPConnectionStatus.DISCONNECTED
        self.tools = []
        self.resources = []
        return True
    
    async def _send_request(self, method: str, params: Dict[str, Any], timeout: float = 60.0) -> Optional[Dict[str, Any]]:
        """Send a JSON-RPC request to the server."""
        if not self._process or not self._process.stdin:
            return None
        
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        
        try:
            # Send request (binary mode, configured encoding)
            request_str = json.dumps(request) + "\n"
            request_bytes = request_str.encode(self._encoding)
            self._process.stdin.write(request_bytes)
            self._process.stdin.flush()
            
            # Read response with timeout using asyncio
            loop = asyncio.get_event_loop()
            
            # Use run_in_executor to make the blocking readline non-blocking
            def read_line():
                line = self._process.stdout.readline()
                return line.decode(self._encoding) if line else None
            
            future = loop.run_in_executor(None, read_line)
            try:
                response_line = await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                self._error_message = f"Request timeout: {method} (timeout={timeout}s)"
                return None
            
            if response_line:
                try:
                    return json.loads(response_line)
                except json.JSONDecodeError as e:
                    self._error_message = f"Invalid JSON response: {response_line[:100]}"
                    return None
        except Exception as e:
            self._error_message = f"Request error: {str(e)}"
        
        return None
    
    async def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._process or not self._process.stdin:
            return
        
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        
        try:
            notification_str = json.dumps(notification) + "\n"
            notification_bytes = notification_str.encode(self._encoding)
            self._process.stdin.write(notification_bytes)
            self._process.stdin.flush()
        except Exception as e:
            self._error_message = str(e)
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool on the MCP server."""
        # Use longer timeout for tool calls (images, etc. may take time)
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        }, timeout=120.0)  # 2 minutes for tool calls
        
        if result and "result" in result:
            return result["result"]
        elif result and "error" in result:
            raise Exception(result["error"].get("message", "Unknown error"))
        
        # Provide more detailed error message
        error_msg = self._error_message or "No response from MCP server"
        raise Exception(f"MCP tool call failed: {error_msg}")
    
    async def list_tools(self) -> List[MCPTool]:
        """List available tools from the server."""
        result = await self._send_request("tools/list", {})
        
        tools = []
        if result and "result" in result:
            for tool_data in result["result"].get("tools", []):
                tools.append(MCPTool(
                    name=tool_data.get("name", ""),
                    description=tool_data.get("description", ""),
                    input_schema=tool_data.get("inputSchema", {}),
                    server_name=self.name,
                ))
        
        return tools
    
    async def list_resources(self) -> List[MCPResource]:
        """List available resources from the server."""
        result = await self._send_request("resources/list", {})
        
        resources = []
        if result and "result" in result:
            for res_data in result["result"].get("resources", []):
                resources.append(MCPResource(
                    uri=res_data.get("uri", ""),
                    name=res_data.get("name", ""),
                    description=res_data.get("description"),
                    mime_type=res_data.get("mimeType"),
                    server_name=self.name,
                ))
        
        return resources


class MCPManager:
    """
    Manager for MCP connections.
    
    Handles:
    - Connection lifecycle
    - Tool discovery and aggregation
    - Tool invocation routing
    """
    
    def __init__(self, encoding: str = "utf-8"):
        self._connections: Dict[str, MCPConnection] = {}
        self._tool_to_server: Dict[str, str] = {}
        self._encoding = encoding
    
    def get_connection(self, name: str) -> Optional[MCPConnection]:
        """Get a connection by name."""
        return self._connections.get(name)
    
    def get_all_connections(self) -> Dict[str, MCPConnection]:
        """Get all connections."""
        return self._connections
    
    async def add_server(self, config: MCPServerConfig) -> bool:
        """Add and optionally connect to an MCP server."""
        if config.name in self._connections:
            return False
        
        connection = StdioMCPConnection(config, encoding=self._encoding)
        self._connections[config.name] = connection
        
        if config.auto_connect:
            return await connection.connect()
        
        return True
    
    async def remove_server(self, name: str) -> bool:
        """Remove an MCP server."""
        connection = self._connections.get(name)
        if not connection:
            return False
        
        await connection.disconnect()
        del self._connections[name]
        
        # Clean up tool mapping
        self._tool_to_server = {
            tool: server for tool, server in self._tool_to_server.items()
            if server != name
        }
        
        return True
    
    async def connect(self, name: str) -> bool:
        """Connect to a specific MCP server."""
        connection = self._connections.get(name)
        if not connection:
            return False
        
        result = await connection.connect()
        if result:
            self._update_tool_mapping()
        return result
    
    async def disconnect(self, name: str) -> bool:
        """Disconnect from a specific MCP server."""
        connection = self._connections.get(name)
        if not connection:
            return False
        
        result = await connection.disconnect()
        if result:
            self._update_tool_mapping()
        return result
    
    async def connect_all(self) -> Dict[str, bool]:
        """Connect to all configured servers."""
        results = {}
        for name, connection in self._connections.items():
            if connection.config.auto_connect:
                results[name] = await connection.connect()
        self._update_tool_mapping()
        return results
    
    async def disconnect_all(self) -> Dict[str, bool]:
        """Disconnect from all servers."""
        results = {}
        for name, connection in self._connections.items():
            results[name] = await connection.disconnect()
        self._tool_to_server = {}
        return results
    
    def _update_tool_mapping(self) -> None:
        """Update the tool to server mapping."""
        self._tool_to_server = {}
        for name, connection in self._connections.items():
            for tool in connection.tools:
                self._tool_to_server[tool.name] = name
    
    def get_all_tools(self) -> List[MCPTool]:
        """Get all tools from all connected servers."""
        tools = []
        for connection in self._connections.values():
            if connection.status == MCPConnectionStatus.CONNECTED:
                tools.extend(connection.tools)
        return tools
    
    def get_all_resources(self) -> List[MCPResource]:
        """Get all resources from all connected servers."""
        resources = []
        for connection in self._connections.values():
            if connection.status == MCPConnectionStatus.CONNECTED:
                resources.extend(connection.resources)
        return resources
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool by name, routing to the correct server."""
        server_name = self._tool_to_server.get(tool_name)
        if not server_name:
            raise ValueError(f"Tool '{tool_name}' not found")
        
        connection = self._connections.get(server_name)
        if not connection:
            raise ValueError(f"Server '{server_name}' not found")
        
        return await connection.call_tool(tool_name, arguments)
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of all MCP connections."""
        return {
            name: {
                "status": conn.status.value,
                "tools_count": len(conn.tools),
                "resources_count": len(conn.resources),
                "error": conn.error_message,
            }
            for name, conn in self._connections.items()
        }
    
    def load_from_config(self, config: Dict[str, Dict[str, Any]]) -> None:
        """Load MCP servers from configuration."""
        for name, server_config in config.items():
            server_config["name"] = name
            self._connections[name] = StdioMCPConnection(
                MCPServerConfig.from_dict(server_config),
                encoding=self._encoding
            )
