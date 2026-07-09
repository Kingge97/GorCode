"""
Model Connector
===============

Connects to LLM providers using GorAI_LLMClient.
"""

import sys
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Generator, AsyncGenerator
from dataclasses import dataclass
import json
import importlib.util

# Setup GorAI_LLMClient path
_llmclient_path = Path(__file__).parent.parent.parent / "GorAI_LLMClient"

# Import from GorAI_LLMClient
HAS_LLMCLIENT = False
create_model = None
ToolExecutor = None
SimpleFunctionExecutor = None

try:
    # Add parent directory to path to enable package imports
    _gorcode_root = Path(__file__).parent.parent.parent
    _gorcode_root_str = str(_gorcode_root.resolve())
    if _gorcode_root_str not in sys.path:
        sys.path.insert(0, _gorcode_root_str)
    
    # Import create_model function
    from GorAI_LLMClient import create_model, ToolExecutor, SimpleFunctionExecutor
    
    HAS_LLMCLIENT = True
except ImportError as e:
    print(f"Warning: Could not import GorAI_LLMClient: {e}")

from GorCode.backend.config.manager import ModelConnection
from GorCode.backend.core.events import EventBus, Event, EventType


@dataclass
class ModelResponse:
    """Response from a model call."""
    
    content: str
    thinking: str = ""
    tool_calls: List[Dict] = None
    is_error: bool = False
    error_message: str = ""
    
    def __post_init__(self):
        if self.tool_calls is None:
            self.tool_calls = []


class ModelConnector:
    """
    Model connector that wraps GorAI_LLMClient.
    
    Provides a unified interface for:
    - Connecting to different LLM providers
    - Streaming responses
    - Tool/function calling
    """
    
    @property
    def SUPPORTED_ROUTERS(self) -> List[str]:
        """Get supported router types from GorAI_LLMClient."""
        if not HAS_LLMCLIENT:
            return []
        # Import router mapping from GorAI_LLMClient
        from GorAI_LLMClient.models import create_model
        import inspect
        source = inspect.getsource(create_model)
        # Extract router names from if/elif conditions
        routers = []
        for line in source.split('\n'):
            line = line.strip()
            if line.startswith('if router == "') or line.startswith('elif router == "'):
                router_name = line.split('"')[1]
                routers.append(router_name)
        return routers
    
    def __init__(
        self,
        connection: ModelConnection,
        event_bus: EventBus = None,
    ):
        """
        Initialize model connector.
        
        Args:
            connection: Model connection configuration
            event_bus: Event bus for communication
        """
        self.connection = connection
        self.event_bus = event_bus or EventBus()
        self._model_instance = None
        self._is_connected = False
    
    @property
    def model_name(self) -> str:
        """Get model name."""
        return self.connection.model_name
    
    @property
    def router(self) -> str:
        """Get router type."""
        return self.connection.router

    @property
    def model_instance_id(self) -> int:
        """Get the identity of the connected model instance."""
        if self._model_instance is None:
            raise RuntimeError("Model is not connected")
        return id(self._model_instance)
    
    def connect(self) -> bool:
        """
        Connect to the model provider.
        
        Returns:
            True if connected successfully
        """
        if not HAS_LLMCLIENT:
            error_msg = "GorAI_LLMClient not available. Please check installation."
            self._emit_error(error_msg)
            print(f"[ModelConnector] Error: {error_msg}")
            return False
        
        try:
            # Validate router
            supported_routers = self.SUPPORTED_ROUTERS
            if self.router not in supported_routers:
                error_msg = f"Unsupported router: {self.router}. Supported: {supported_routers}"
                self._emit_error(error_msg)
                print(f"[ModelConnector] Error: {error_msg}")
                return False
            
            # Validate required fields
            if not self.connection.api_key or self.connection.api_key == "YOUR_API_KEY_HERE":
                error_msg = f"Invalid API key for model '{self.connection.name}'. Please configure in ~/.gorcode/config.json"
                self._emit_error(error_msg)
                print(f"[ModelConnector] Error: {error_msg}")
                return False
            
            if not self.connection.base_url:
                error_msg = f"Missing base_url for model '{self.connection.name}'"
                self._emit_error(error_msg)
                print(f"[ModelConnector] Error: {error_msg}")
                return False
            
            # Create model instance using create_model
            self._model_instance = create_model(
                base_url=self.connection.base_url,
                api_key=self.connection.api_key,
                model_name=self.connection.model_name,
                stream=self.connection.stream,
                extra_args=self.connection.extra_args,
                router=self.connection.router,
            )
            
            self._is_connected = True
            return True
            
        except Exception as e:
            error_msg = f"Failed to connect: {str(e)}"
            self._emit_error(error_msg)
            print(f"[ModelConnector] Error: {error_msg}")
            return False
    
    def disconnect(self) -> None:
        """Disconnect from the model provider."""
        self._model_instance = None
        self._is_connected = False
    
    def _emit_error(self, message: str) -> None:
        """Emit an error event."""
        self.event_bus.emit(EventType.MODEL_ERROR, {"error": message})
    
    def _emit_thinking(self, content: str) -> None:
        """Emit a thinking event."""
        self.event_bus.emit(EventType.MODEL_THINKING, {"content": content})
    
    def _emit_answer(self, content: str) -> None:
        """Emit an answer event."""
        self.event_bus.emit(EventType.MODEL_ANSWER, {"content": content})
    
    def _emit_tool_call(self, tool_name: str, arguments: Dict) -> None:
        """Emit a tool call event."""
        self.event_bus.emit(EventType.MODEL_TOOL_CALL, {
            "name": tool_name,
            "arguments": arguments,
        })
    
    def init_tools(self, tools: List[Dict]) -> None:
        """
        Initialize tools for the model.
        
        Args:
            tools: List of tool definitions
        """
        if self._model_instance:
            self._model_instance.model_tool_init(tools)

    def add_hook(
        self,
        event: str,
        handler,
        priority: int = 0,
        name: str | None = None,
    ):
        """Forward hook registration to the underlying LLMClient model."""
        if not self._model_instance:
            raise RuntimeError("Model is not connected")
        return self._model_instance.add_hook(
            event,
            handler,
            priority=priority,
            name=name,
        )

    def remove_hook(
        self,
        event: str,
        handler_or_name,
    ) -> int:
        """Forward hook removal to the underlying LLMClient model."""
        if not self._model_instance:
            raise RuntimeError("Model is not connected")
        return self._model_instance.remove_hook(event, handler_or_name)
    
    def chat(
        self,
        messages: List[Dict],
        tools: List[Dict] = None,
    ) -> Generator[ModelResponse, None, None]:
        """
        Chat with the model.
        
        Args:
            messages: List of messages
            tools: Optional list of tools
            
        Yields:
            ModelResponse objects (streaming, each contains partial content)
        """
        if not self._is_connected or self._model_instance is None:
            yield ModelResponse(
                content="",
                is_error=True,
                error_message="Not connected to model",
            )
            return
        
        try:
            # Initialize tools if provided
            if tools is not None:
                self.init_tools(tools)
            
            # Call model
            response = self._model_instance.model_chat(messages)
            
            thinking = ""
            answer = ""
            tool_calls = []
            
            for item in response:
                if item.gorType == "think":
                    thinking += item.content
                    # 不再通过 EventBus 发送，只通过 yield 返回
                    # self._emit_thinking(item.content)
                    # Yield thinking content immediately for streaming
                    yield ModelResponse(
                        content="",
                        thinking=item.content,
                        tool_calls=[],
                    )
                    
                elif item.gorType == "answer":
                    answer += item.content
                    # 不再通过 EventBus 发送，只通过 yield 返回
                    # self._emit_answer(item.content)
                    # Yield answer content immediately for streaming
                    yield ModelResponse(
                        content=item.content,
                        thinking="",
                        tool_calls=[],
                    )
                    
                elif item.gorType == "tool":
                    try:
                        tool_call = json.loads(item.content)
                        tool_calls.append(tool_call)
                        # 不再通过 EventBus 发送，由 executor.py 统一处理
                        # self._emit_tool_call(
                        #     tool_call["function"]["name"],
                        #     json.loads(tool_call["function"]["arguments"]),
                        # )
                    except (json.JSONDecodeError, KeyError):
                        pass
                        
                elif item.gorType == "connection_error":
                    yield ModelResponse(
                        content="",
                        is_error=True,
                        error_message=item.content,
                    )
                    return

                elif item.gorType == "error":
                    yield ModelResponse(
                        content="",
                        is_error=True,
                        error_message=item.content,
                    )
                    return
            
            # Yield final response with tool calls if any
            # Note: Don't include answer/thinking here as they've already been yielded incrementally
            if tool_calls:
                yield ModelResponse(
                    content="",
                    thinking="",
                    tool_calls=tool_calls,
                )
            
        except Exception as e:
            yield ModelResponse(
                content="",
                is_error=True,
                error_message=str(e),
            )
    
    def chat_to_next_loop(
        self,
        messages: List[Dict],
        executor: 'ToolExecutor',
        tools: List[Dict] = None,
        interrupt_check: callable = None,
    ) -> Generator[Dict, None, None]:
        """
        Chat until the model returns a final response (no more tool calls).
        
        This wraps GorAI_LLMClient's chatToNextLoop method.
        
        Args:
            messages: List of messages (will be modified in place)
            executor: Tool executor
            tools: Optional list of tools
            interrupt_check: Optional function to check for interruption
            
        Yields:
            Event dictionaries
        """
        if not self._is_connected or self._model_instance is None:
            yield {"type": "error", "message": "Not connected to model"}
            return
        
        try:
            # Initialize tools if provided
            if tools is not None:
                self.init_tools(tools)
            
            # Use chatToNextLoop from GorAI_LLMClient
            for event_bytes in self._model_instance.chatToNextLoop(
                messages=messages,
                executor=executor,
                interrupt_check=interrupt_check,
            ):
                # Parse the SSE event
                if event_bytes.startswith(b"data: "):
                    try:
                        event_str = event_bytes[6:].decode('utf-8').strip()
                        if event_str:
                            event = json.loads(event_str)
                            yield event
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass
                        
        except Exception as e:
            yield {"type": "error", "message": str(e)}


class ModelManager:
    """
    Manager for multiple model connections.
    
    Handles:
    - Multiple model configurations
    - Model switching
    - Connection pooling
    """
    
    def __init__(self, event_bus: EventBus = None):
        """
        Initialize model manager.
        
        Args:
            event_bus: Event bus for communication
        """
        self.event_bus = event_bus or EventBus()
        self._connectors: Dict[str, ModelConnector] = {}
        self._current_model: str = None
    
    def register(self, connection: ModelConnection) -> bool:
        """
        Register a model connection.
        
        Args:
            connection: Model connection configuration
            
        Returns:
            True if registered successfully
        """
        connector = ModelConnector(connection, self.event_bus)
        self._connectors[connection.name] = connector
        return True
    
    def connect(self, name: str) -> bool:
        """
        Connect to a registered model.
        
        Args:
            name: Model name
            
        Returns:
            True if connected successfully
        """
        if name not in self._connectors:
            return False
        
        connector = self._connectors[name]
        if connector.connect():
            self._current_model = name
            return True
        return False
    
    def disconnect(self, name: str = None) -> None:
        """
        Disconnect from a model.
        
        Args:
            name: Model name, or None for current model
        """
        name = name or self._current_model
        if name and name in self._connectors:
            self._connectors[name].disconnect()
            if self._current_model == name:
                self._current_model = None
    
    def get(self, name: str = None) -> Optional[ModelConnector]:
        """
        Get a model connector.
        
        Args:
            name: Model name, or None for current model
            
        Returns:
            Model connector or None
        """
        name = name or self._current_model
        return self._connectors.get(name)
    
    def current(self) -> Optional[ModelConnector]:
        """Get the current model connector."""
        return self.get()
    
    def list_models(self) -> List[str]:
        """List registered model names."""
        return list(self._connectors.keys())
    
    @property
    def current_model_name(self) -> Optional[str]:
        """Get the current model name."""
        return self._current_model
