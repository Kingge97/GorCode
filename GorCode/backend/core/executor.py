"""
Backend Executor
===============

Main backend executor that coordinates model calls, tool execution, and agent management.
"""

from typing import Any, Dict, List, Optional, Generator, AsyncGenerator
from dataclasses import dataclass
import json
import sys
import os
import time

from .events import EventBus, Event, EventType
from .model_connector import ModelConnector, ModelManager
from ..config.manager import ConfigManager, ModelConnection
from ..tools.base import ToolRegistry, ToolResult
from ..agents.base import AgentRegistry, AgentInfo
from ..session import SessionManager, SessionStorage, DebugLogger
from ..permission import get_permission_manager, PermissionType, PermissionResponse
from ..context import (
    TokenEstimator,
    CompactionManager,
    CompactionConfig,
    ResponseCache,
    StreamingOptimizer,
)
from ..skills import SkillLoader, SkillInjector

# Import ToolExecutor from GorAI_LLMClient
try:
    from GorAI_LLMClient.executor import ToolExecutor
    HAS_TOOL_EXECUTOR = True
except ImportError:
    HAS_TOOL_EXECUTOR = False
    # Fallback: create a local abstract base class
    from abc import ABC, abstractmethod
    
    class ToolExecutor(ABC):
        @abstractmethod
        def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
            pass


class UserRejectionError(Exception):
    """
    用户拒绝操作且未提供理由的异常。
    
    当用户在权限对话框选择拒绝但不输入理由时抛出此异常，
    用于触发对话回退机制。
    """
    pass


class GorCodeToolExecutor(ToolExecutor):
    """
    ToolExecutor implementation that wraps GorCode's ToolRegistry.
    
    This class bridges GorAI_LLMClient's tool execution interface with GorCode's ToolRegistry.
    """
    
    def __init__(self, tool_registry: ToolRegistry, event_bus: EventBus = None, 
                 permission_manager=None, permission_callback=None, backend_state=None):
        """
        Initialize the executor.
        
        Args:
            tool_registry: GorCode's tool registry
            event_bus: Event bus for emitting tool execution events
            permission_manager: Permission manager for session permissions
            permission_callback: Callback for permission UI
            backend_state: Backend state for setting flags
        """
        self.tool_registry = tool_registry
        self.event_bus = event_bus
        self._permission_manager = permission_manager
        self._permission_callback = permission_callback
        self._backend_state = backend_state
        self._user_rejected_without_reason = False  # Flag for rejection without reason
        self._current_skill_context: Optional[Dict[str, Any]] = None  # Track skill context for path resolution
    
    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        Execute a tool by name with the given arguments.
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            
        Returns:
            Tool execution result as string
        """
        if self.tool_registry is None:
            return f"Error: Tool registry not available"
        
        # Handle Skill tool - capture skill context for subsequent bash commands
        if tool_name == "Skill":
            result = self.tool_registry.execute(tool_name, **arguments)
            # Capture skill context from metadata
            if result.metadata and result.metadata.get("skill_dir"):
                self._current_skill_context = {
                    "skill_name": result.metadata.get("skill_name"),
                    "skill_dir": result.metadata.get("skill_dir"),
                }
            if result.success:
                return result.output
            else:
                return f"Error: {result.error}" if result.error else "Error: Skill loading failed"
        
        # Handle Bash tool with skill context
        if tool_name == "bash" and self._current_skill_context:
            tool = self.tool_registry.get(tool_name)
            if tool:
                # Execute with skill context for path resolution
                command = arguments.get("command", "")
                timeout = arguments.get("timeout", 60)
                cwd = arguments.get("cwd")
                skill_dir = self._current_skill_context.get("skill_dir")
                
                # Use execute_with_skill_context if available
                if hasattr(tool, 'execute_with_skill_context'):
                    result = tool.execute_with_skill_context(
                        command=command,
                        timeout=timeout,
                        cwd=cwd,
                        skill_dir=skill_dir
                    )
                else:
                    result = self.tool_registry.execute(tool_name, **arguments)
                
                # Handle permission for bash
                if result.metadata and result.metadata.get("requires_permission"):
                    return self._handle_bash_permission(tool, result, arguments)
                
                if result.success:
                    return result.output if result.output else "Command executed successfully"
                else:
                    # Return error with output if available (e.g., timeout with partial logs)
                    if result.error:
                        return f"Error: {result.error}"
                    elif result.output:
                        return result.output
                    else:
                        return "Error: Command execution failed"
        
        # Check if tool requires permission
        tool = self.tool_registry.get(tool_name)
        if tool and getattr(tool, 'requires_permission', False):
            # Execute in preview mode first to get metadata
            result = self.tool_registry.execute(tool_name, **arguments)
            
            if result.metadata and result.metadata.get("requires_permission"):
                return self._handle_tool_permission(tool_name, tool, result, arguments)
            
            # Return result
            if result.success:
                return result.output if result.output else "Command executed successfully"
            else:
                # Return error with output if available
                if result.error:
                    return f"Error: {result.error}"
                elif result.output:
                    return result.output
                else:
                    return "Error: Tool execution failed"
        else:
            # Tool doesn't require permission - execute directly
            result = self.tool_registry.execute(tool_name, **arguments)
        
        if result.success:
            return result.output
        else:
            # Return error with output if available
            if result.error:
                return f"Error: {result.error}"
            elif result.output:
                return result.output
            else:
                return "Error: Tool execution failed"
    
    def _handle_tool_permission(self, tool_name: str, tool, result: ToolResult, arguments: Dict[str, Any]) -> str:
        """Handle permission check and execution for tools."""
        # Import here to avoid circular dependency
        from backend.permission import PermissionType
        
        # Determine permission type
        permission_type = None
        if tool_name == "write":
            permission_type = PermissionType.WRITE
        elif tool_name == "edit":
            permission_type = PermissionType.EDIT
        elif tool_name == "bash":
            if result.metadata.get("has_delete"):
                permission_type = PermissionType.BASH_DELETE
            else:
                permission_type = PermissionType.BASH
        
        if permission_type and self._permission_manager:
            # Check if already has session permission
            if not self._permission_manager.has_session_permission(permission_type):
                # Request permission
                if self._permission_callback:
                    callback_result = self._permission_callback(permission_type.value, result.metadata)
                    
                    # Handle tuple result (response, reason)
                    if isinstance(callback_result, tuple):
                        response, reason = callback_result
                    else:
                        # Backward compatibility
                        response = callback_result
                        reason = None
                    
                    if response == "always":
                        self._permission_manager.grant_session_permission(permission_type)
                    elif response == "once":
                        pass  # Allow this time
                    else:  # reject
                        # Check if reason is provided
                        if reason and reason.strip():
                            # 有理由：返回错误让AI知道
                            return f"Error: 操作被用户拒绝 - {reason}"
                        else:
                            # 无理由：设置标志并返回错误
                            self._user_rejected_without_reason = True
                            if self._backend_state:
                                self._backend_state.user_rejected_without_reason = True
                            return "Error: 用户拒绝操作且未提供理由"
                else:
                    # No callback - reject by default
                    return "Error: Permission denied (no callback set)"
            
            # Permission granted - execute with permission
            if tool_name in ("write", "edit"):
                if hasattr(tool, 'execute_with_permission'):
                    if tool_name == "write":
                        result = tool.execute_with_permission(
                            file_path=result.metadata.get("file_path"),
                            content=result.metadata.get("content"),
                            encoding=result.metadata.get("encoding", "utf-8")
                        )
                    elif tool_name == "edit":
                        result = tool.execute_with_permission(
                            file_path=result.metadata.get("file_path"),
                            new_content=result.metadata.get("new_content"),
                            encoding=result.metadata.get("encoding", "utf-8")
                        )
            elif tool_name == "bash":
                return self._handle_bash_execution(tool, result)
        
        if result.success:
            return result.output if result.output else "Command executed successfully"
        else:
            return f"Error: {result.error}" if result.error else "Error: Tool execution failed"
    
    def _handle_bash_permission(self, tool, result: ToolResult, arguments: Dict[str, Any]) -> str:
        """Handle permission specifically for bash tool with skill context."""
        # Import here to avoid circular dependency
        from backend.permission import PermissionType
        
        permission_type = PermissionType.BASH_DELETE if result.metadata.get("has_delete") else PermissionType.BASH
        
        if self._permission_manager and not self._permission_manager.has_session_permission(permission_type):
            if self._permission_callback:
                callback_result = self._permission_callback(permission_type.value, result.metadata)
                
                if isinstance(callback_result, tuple):
                    response, reason = callback_result
                else:
                    response = callback_result
                    reason = None
                
                if response == "always":
                    self._permission_manager.grant_session_permission(permission_type)
                elif response == "once":
                    pass
                else:  # reject
                    if reason and reason.strip():
                        return f"Error: 操作被用户拒绝 - {reason}"
                    else:
                        self._user_rejected_without_reason = True
                        if self._backend_state:
                            self._backend_state.user_rejected_without_reason = True
                        return "Error: 用户拒绝操作且未提供理由"
            else:
                return "Error: Permission denied (no callback set)"
        
        return self._handle_bash_execution(tool, result)
    
    def _handle_bash_execution(self, tool, result: ToolResult) -> str:
        """Execute bash command with permission."""
        if hasattr(tool, 'execute_with_permission'):
            result = tool.execute_with_permission(
                command=result.metadata.get("command"),
                timeout=result.metadata.get("timeout", 60),
                cwd=result.metadata.get("cwd")
            )
        
        if result.success:
            return result.output if result.output else "Command executed successfully"
        else:
            # Return error with output if available (e.g., timeout with partial logs)
            if result.error:
                return f"Error: {result.error}"
            elif result.output:
                return result.output
            else:
                return "Error: Command execution failed"


@dataclass
class BackendState:
    """State of the backend executor."""
    
    current_agent: str = "build"
    current_model: str = "main"
    is_running: bool = False
    is_interrupted: bool = False
    user_rejected_without_reason: bool = False  # Flag for rejection without reason
    messages: List[Dict] = None
    token_count: int = 0  # Track current token count
    
    def __post_init__(self):
        if self.messages is None:
            self.messages = []


class BackendExecutor:
    """
    Main backend executor for GorCode.
    
    Coordinates:
    - Model connection and chat loop
    - Tool execution
    - Agent management
    - Event communication with frontend
    - Session management
    - Debug logging
    - Context compaction
    - Response caching
    """
    
    def __init__(self, event_bus: EventBus = None):
        self.event_bus = event_bus or EventBus()
        self.state = BackendState()
        self._model_manager: ModelManager = None
        self._config_manager: ConfigManager = None
        self._tool_registry: ToolRegistry = None
        self._agent_registry: AgentRegistry = None
        self._session_manager: SessionManager = None
        self._debug_logger: DebugLogger = None
        self._compaction_manager: CompactionManager = None
        self._response_cache: ResponseCache = None
        self._streaming_optimizer: StreamingOptimizer = None
        self._skill_loader: SkillLoader = None
        self._skill_injector: SkillInjector = None
        
        # Permission management
        self._permission_manager = get_permission_manager()
        self._permission_callback = None  # Set by frontend
        self._reconnect_callback = None  # Set by frontend
        self._reconnect_wait_seconds = 5
        self._pending_reconnect_success = False
        self._reconnect_failure_count = 0
        self._reconnect_max_failures = 5
    
    def initialize(
        self,
        config_manager: ConfigManager = None,
        tool_registry: ToolRegistry = None,
        agent_registry: AgentRegistry = None,
    ) -> None:
        """
        Initialize the executor with required components.
        
        Args:
            config_manager: Configuration manager
            tool_registry: Tool registry
            agent_registry: Agent registry
        """
        self._config_manager = config_manager
        self._tool_registry = tool_registry or ToolRegistry()
        self._agent_registry = agent_registry or AgentRegistry()
        
        # Initialize model manager if config is available
        if config_manager:
            self._init_model_manager()
            self._init_session_manager()
            self._init_debug_logger()
            self._init_context_management()
            self._init_skill_system()
    
    def set_permission_callback(self, callback):
        """
        Set permission callback for UI interaction.
        
        Args:
            callback: Async function(request_id, permission_type, metadata) -> PermissionResponse
        """
        self._permission_callback = callback
        self._permission_manager.set_permission_callback(callback)

    def set_reconnect_callback(self, callback):
        """
        Set reconnect callback for UI interaction.
        
        Args:
            callback: Function(error_message: str) -> str ("1" to retry, "2" to stop)
        """
        self._reconnect_callback = callback

    def _attempt_reconnect(self) -> bool:
        """Attempt to reconnect the current model."""
        if not self._model_manager:
            return False
        
        model_name = self._model_manager.current_model_name or self.state.current_model
        if not model_name:
            return False
        
        # Force disconnect and reconnect
        self._model_manager.disconnect(model_name)
        if self._model_manager.connect(model_name):
            self.state.current_model = model_name
            return True
        
        return False

    def _emit_reconnect_success_if_pending(self, event: Dict[str, Any]) -> None:
        """Emit reconnect success message once when the next non-connection event arrives."""
        if not self._pending_reconnect_success:
            return
        if self._is_connection_error_event(event):
            # Reconnected but immediately failed again; clear pending success.
            self._pending_reconnect_success = False
            return
        self._pending_reconnect_success = False
        self._reconnect_failure_count = 0
        self.emit(EventType.UI_MESSAGE, {"message": "重连成功，继续对话..."})

    def _reset_reconnect_failures_on_normal_event(self, event: Dict[str, Any]) -> None:
        """Reset reconnect failure counter when normal events are received."""
        if self._is_connection_error_event(event):
            return
        if self._reconnect_failure_count != 0:
            self._reconnect_failure_count = 0

    def _sync_messages_from_system(self, messages_with_system: List[Dict]) -> None:
        """Sync messages (excluding system prompt) back to state and session."""
        if len(messages_with_system) > 1:
            self.state.messages = messages_with_system[1:].copy()
            if self._session_manager:
                self._session_manager.set_messages(self.state.messages)

    def _extract_connection_error_message(self, event: Dict[str, Any]) -> Optional[str]:
        """Extract connection error message if this event represents a connection issue."""
        event_type = event.get("type", "")
        msg = event.get("message") or event.get("content") or event.get("error") or ""
        msg_lower = msg.lower() if isinstance(msg, str) else ""
        
        if event_type == "connection_error":
            return msg or "connection_error"
        
        keywords = [
            "connection_error",
            "connection error",
            "connectionerror",
            "econn",
            "connection reset",
            "timed out",
            "timeout",
            "network error",
            "network_error",
        ]
        if any(k in msg_lower for k in keywords):
            return msg or "connection_error"
        
        return None

    def _is_connection_error_event(self, event: Dict[str, Any]) -> bool:
        """Check whether an event represents a connection error."""
        return self._extract_connection_error_message(event) is not None

    def _handle_connection_error(
        self,
        event: Dict[str, Any],
        messages_with_system: List[Dict],
    ) -> Generator[Event, None, bool]:
        """
        Handle connection error with retry logic.
        
        Returns:
            True to retry chat loop, False to stop and wait for user input.
        """
        error_msg = self._extract_connection_error_message(event) or "连接已断开"
        yield Event(EventType.UI_MESSAGE, {"message": f"连接断开：{error_msg}"})
        
        while True:
            if self._reconnect_failure_count >= self._reconnect_max_failures:
                # Reconnect failed too many times, ask user
                choice = "2"
                if self._reconnect_callback:
                    try:
                        choice = self._reconnect_callback(error_msg)
                    except Exception:
                        choice = "2"
                
                if str(choice).strip() == "1":
                    self._reconnect_failure_count = 0
                    yield Event(EventType.UI_MESSAGE, {"message": "将继续尝试重连..."})
                else:
                    # Stop retrying, sync current messages and wait for next user input
                    self._sync_messages_from_system(messages_with_system)
                    yield Event(EventType.UI_MESSAGE, {"message": "已停止重连，等待用户下一次输入。"})
                    return False
            
            yield Event(EventType.UI_MESSAGE, {
                "message": f"将在 {self._reconnect_wait_seconds}s 后尝试重连..."
            })
            time.sleep(self._reconnect_wait_seconds)
            
            if self._attempt_reconnect():
                # Delay success message until we get a non-connection event.
                self._pending_reconnect_success = True
                return True
            
            # Reconnect failed, increment failure count
            self._reconnect_failure_count += 1
    
    async def _check_permission(
        self,
        permission_type: PermissionType,
        metadata: Dict[str, Any]
    ) -> PermissionResponse:
        """
        Check if permission is granted for an operation.
        
        Args:
            permission_type: Type of permission needed
            metadata: Permission metadata
            
        Returns:
            PermissionResponse from user
        """
        # Emit permission request event
        self.emit(EventType.PERMISSION_REQUEST, {
            "permission_type": permission_type.value,
            "metadata": metadata,
        })
        
        # Request permission from user
        response = await self._permission_manager.request_permission(
            permission_type,
            metadata
        )
        
        # Emit permission response event
        self.emit(EventType.PERMISSION_RESPONSE, {
            "permission_type": permission_type.value,
            "response": response.value,
        })
        
        return response
    
    def _init_context_management(self) -> None:
        """Initialize context management (compaction, cache, streaming)."""
        # Initialize compaction manager
        compaction_config = CompactionConfig(
            context_limit=self._config_manager.config.max_context_length if self._config_manager else 128000,
            auto_compact=True,
        )
        self._compaction_manager = CompactionManager(
            event_bus=self.event_bus,
            config=compaction_config,
            model_manager=self._model_manager,
        )
        
        # Initialize response cache
        self._response_cache = ResponseCache()
        
        # Initialize streaming optimizer
        self._streaming_optimizer = StreamingOptimizer()
    
    def _init_model_manager(self) -> None:
        """Initialize model manager from configuration."""
        self._model_manager = ModelManager(self.event_bus)
        
        config = self._config_manager.config
        for name, connection in config.model_connections.items():
            self._model_manager.register(connection)
        
        # Initialize TaskTool with model connector if available
        self._init_task_tool()
    
    def _init_session_manager(self) -> None:
        """Initialize session manager."""
        project_path = str(self._config_manager.project_path) if self._config_manager else ""
        self._session_manager = SessionManager(
            event_bus=self.event_bus,
            storage=SessionStorage(),
            project_path=project_path,
        )
        
        # Create initial session
        self._session_manager.create_session(
            agent=self.state.current_agent,
            model=self.state.current_model,
        )
    
    def _init_debug_logger(self) -> None:
        """Initialize debug logger."""
        project_path = str(self._config_manager.project_path) if self._config_manager else ""
        debug_mode = self._config_manager.config.debug_mode if self._config_manager else False
        
        self._debug_logger = DebugLogger(
            base_path=project_path,
            enabled=debug_mode,
        )
        
        if debug_mode and self._session_manager:
            session = self._session_manager.current_session
            self._debug_logger.start_session(
                self.state.current_agent,
                session.session_id if session else None
            )
    
    def _init_task_tool(self) -> None:
        """Initialize TaskTool with config manager for dynamic model selection."""
        if self._tool_registry:
            task_tool = self._tool_registry.get("Task")
            if task_tool:
                # 总是设置 event_bus，即使模型没有配置
                task_tool.set_event_bus(self.event_bus)
                task_tool.set_parent_agent_name(self.state.current_agent)
                
                # 设置 agent 和 tool registry
                task_tool.set_agent_registry(self._agent_registry)
                task_tool.set_tool_registry(self._tool_registry)
                
                # 设置 config_manager，让 TaskTool 根据 agent_model_mapping 动态选择模型
                if hasattr(task_tool, 'set_config_manager') and self._config_manager:
                    task_tool.set_config_manager(self._config_manager)
    
    def _init_skill_system(self) -> None:
        """Initialize skill system and configure SkillTool."""
        # Initialize skill loader
        self._skill_loader = SkillLoader()
        
        # Add search paths using the new multi-source initialization
        if self._config_manager:
            project_path = str(self._config_manager.project_path)
            self._skill_loader.initialize_default_paths(project_path)
            
            # Also add user-level skills
            user_skills_dir = self._config_manager.get_user_config_dir() / "skills"
            if user_skills_dir.exists():
                self._skill_loader.add_search_path(str(user_skills_dir))
        
        # Load all discovered skills
        self._skill_loader.load_all_skills()
        
        # Create skill injector
        self._skill_injector = SkillInjector(self._skill_loader)
        
        # Configure SkillTool with skill loader
        if self._tool_registry:
            skill_tool = self._tool_registry.get("Skill")
            if skill_tool and hasattr(skill_tool, 'set_skill_loader'):
                skill_tool.set_skill_loader(self._skill_loader)
        
        # Log loaded skills
        skills = self._skill_loader.get_all_skills()
        if skills:
            print(f"[Executor] Loaded {len(skills)} skill(s): {', '.join(skills.keys())}")
    
    @property
    def model(self) -> Optional[ModelConnector]:
        """Get current model connector."""
        if self._model_manager:
            return self._model_manager.current()
        return None
    
    @property
    def config(self) -> Optional[ConfigManager]:
        """Get configuration manager."""
        return self._config_manager
    
    @property
    def tool_registry(self) -> ToolRegistry:
        """Get tool registry."""
        return self._tool_registry
    
    @tool_registry.setter
    def tool_registry(self, value: ToolRegistry) -> None:
        """Set tool registry."""
        self._tool_registry = value
    
    @property
    def agent_registry(self) -> AgentRegistry:
        """Get agent registry."""
        return self._agent_registry
    
    @agent_registry.setter
    def agent_registry(self, value: AgentRegistry) -> None:
        """Set agent registry."""
        self._agent_registry = value
    
    @property
    def session_manager(self) -> Optional[SessionManager]:
        """Get session manager."""
        return self._session_manager
    
    @property
    def debug_logger(self) -> Optional[DebugLogger]:
        """Get debug logger."""
        return self._debug_logger
    
    @property
    def compaction_manager(self) -> Optional[CompactionManager]:
        """Get compaction manager."""
        return self._compaction_manager
    
    @property
    def response_cache(self) -> Optional[ResponseCache]:
        """Get response cache."""
        return self._response_cache
    
    def get_token_usage(self) -> Dict[str, Any]:
        """
        Get current token usage statistics.
        
        Returns:
            Token usage dictionary
        """
        self.state.token_count = TokenEstimator.estimate_messages(self.state.messages)
        
        if self._compaction_manager:
            usage = self._compaction_manager.get_token_usage(self.state.messages)
            usage["current_count"] = self.state.token_count
            return usage
        
        return {
            "current_tokens": self.state.token_count,
            "context_limit": 128000,
            "usage_percentage": round(self.state.token_count / 128000 * 100, 1),
        }
    
    def check_context_overflow(self) -> bool:
        """
        Check if context is approaching overflow (soft threshold).
        
        Returns:
            True if overflow detected
        """
        if self._compaction_manager:
            return self._compaction_manager.check_soft_compact_needed(self.state.messages)
        return False
    
    def check_context_hard_overflow(self) -> bool:
        """
        Check if context exceeds hard threshold.
        
        Returns:
            True if hard overflow detected
        """
        if self._compaction_manager:
            return self._compaction_manager.check_hard_compact_needed(self.state.messages)
        return False
    
    def _auto_compact_context(self) -> Generator[Event, None, None]:
        """
        Automatically compact context when token threshold is reached.
        
        This is called internally during the chat loop when context grows too large.
        
        Yields:
            Event objects for frontend to process
        """
        if not self._compaction_manager:
            return
        
        # Get token usage before compaction
        usage_before = self._compaction_manager.get_token_usage(self.state.messages)
        
        # Perform compaction
        result = self._compaction_manager.compact(self.state.messages)
        
        if result.success and result.compaction_type != "none":
            # Update messages with compacted version
            self.state.messages = result.messages
            self.state.token_count = result.compacted_tokens
            
            # Sync with session manager
            if self._session_manager:
                self._session_manager.set_messages(self.state.messages)
            
            # Build status message based on compaction type
            if result.is_hard_compaction:
                status_msg = f"🗜️ Hard compaction: {result.original_tokens} -> {result.compacted_tokens} tokens ({result.compression_ratio:.1f}x)"
            elif result.is_soft_compaction:
                status_msg = f"🗜️ Soft compaction: {result.original_tokens} -> {result.compacted_tokens} tokens ({result.compression_ratio:.1f}x)"
            else:
                status_msg = f"🗜️ Context compacted: {result.original_tokens} -> {result.compacted_tokens} tokens"
            
            # Emit compaction event
            yield Event(EventType.UI_MESSAGE, {"message": status_msg})
            
            # Emit compaction summary if available (full text, no truncation)
            if result.summary:
                summary_msg = f"[Compaction Summary] {result.summary}"
                yield Event(EventType.UI_MESSAGE, {"message": summary_msg})
            
            # Emit compaction details event
            self.emit(EventType.SESSION_SAVE, {
                "action": "auto_compaction",
                "compaction_type": result.compaction_type,
                "original_tokens": result.original_tokens,
                "compacted_tokens": result.compacted_tokens,
                "compression_ratio": result.compression_ratio,
            })
    
    def compact_context(self, force: bool = False, force_soft: bool = False) -> Dict[str, Any]:
        """
        Compact the conversation context using two-phase strategy.
        
        Args:
            force: Force hard compaction even if not needed
            force_soft: Force soft compaction even if not needed
            
        Returns:
            Compaction result
        """
        if not self._compaction_manager:
            return {"success": False, "error": "Compaction not initialized"}
        
        result = self._compaction_manager.compact(self.state.messages, force=force, force_soft=force_soft)
        
        if result.success:
            # Update messages with compacted version
            self.state.messages = result.messages
            self.state.token_count = result.compacted_tokens
            
            # Sync with session manager
            if self._session_manager:
                self._session_manager.set_messages(self.state.messages)
            
            # Build status message based on compaction type
            if result.is_hard_compaction:
                status_msg = f"Hard compaction: {result.original_tokens} -> {result.compacted_tokens} tokens ({result.compression_ratio:.1f}x)"
            elif result.is_soft_compaction:
                status_msg = f"Soft compaction: {result.original_tokens} -> {result.compacted_tokens} tokens ({result.compression_ratio:.1f}x)"
            else:
                status_msg = f"Context compacted: {result.original_tokens} -> {result.compacted_tokens} tokens"
            
            self.emit(EventType.UI_MESSAGE, {"message": status_msg})
            
            # Emit compaction summary if available (full text, no truncation)
            if result.summary:
                summary_msg = f"[Compaction Summary] {result.summary}"
                self.emit(EventType.UI_MESSAGE, {"message": summary_msg})
        
        return {
            "success": result.success,
            "original_tokens": result.original_tokens,
            "compacted_tokens": result.compacted_tokens,
            "compression_ratio": result.compression_ratio,
            "pruned_tool_results": result.pruned_tool_results,
            "cleared_tool_results": result.cleared_tool_results,
            "compaction_type": result.compaction_type,
            "protected_tool_calls": result.protected_tool_calls,
            "summary": result.summary,
            "error": result.error,
        }
    
    def emit(self, event_type: EventType, data: Any = None) -> None:
        """Emit an event through the event bus."""
        self.event_bus.emit(event_type, data, source="backend")
    
    def switch_agent(self, agent_name: str) -> bool:
        """
        Switch to a different agent.
        
        Args:
            agent_name: Name of the agent to switch to
            
        Returns:
            True if switch was successful, False otherwise
        """
        if self._agent_registry and agent_name in self._agent_registry.agents:
            self.state.current_agent = agent_name
            self.emit(EventType.AGENT_SWITCH, {"agent": agent_name})
            
            # 更新 TaskTool 的父代理名
            if self._tool_registry:
                task_tool = self._tool_registry.get("Task")
                if task_tool and hasattr(task_tool, 'set_parent_agent_name'):
                    task_tool.set_parent_agent_name(agent_name)
            
            # Switch to agent's preferred model
            if self._config_manager:
                agent_model = self._config_manager.get_agent_model(agent_name)
                if agent_model:
                    self.switch_model(agent_model.name)
            
            return True
        return False
    
    def switch_model(self, model_name: str) -> bool:
        """
        Switch to a different model.
        
        Args:
            model_name: Name of the model configuration to use
            
        Returns:
            True if switch was successful, False otherwise
        """
        if self._model_manager is None:
            self.emit(EventType.UI_MESSAGE, {"message": "Model manager not initialized"})
            return False
        
        if model_name not in self._model_manager.list_models():
            self.emit(EventType.UI_MESSAGE, {"message": f"Model '{model_name}' not found. Available: {self._model_manager.list_models()}"})
            return False
        
        # Disconnect current model if different
        if self._model_manager.current_model_name != model_name:
            self._model_manager.disconnect()
        
        # Connect to new model
        if self._model_manager.connect(model_name):
            self.state.current_model = model_name
            self.emit(EventType.UI_MESSAGE, {"message": f"Switched to model: {model_name}"})
            return True
        
        self.emit(EventType.UI_MESSAGE, {"message": f"Failed to connect to model: {model_name}"})
        return False
    
    def check_interrupt(self) -> bool:
        """Check if execution should be interrupted."""
        return self.state.is_interrupted
    
    def set_interrupt(self, value: bool = True) -> None:
        """Set interrupt flag."""
        self.state.is_interrupted = value
        if value:
            self.emit(EventType.SYSTEM_INTERRUPT, {"message": "Execution interrupted"})
    
    def get_current_agent(self) -> Optional[AgentInfo]:
        """Get current agent info."""
        if self._agent_registry:
            return self._agent_registry.get(self.state.current_agent)
        return None
    
    def get_system_prompt(self) -> str:
        """Get system prompt for current agent."""
        agent = self.get_current_agent()
        if agent and agent.prompt:
            prompt = agent.prompt.format(workdir=self._get_workdir())
            
            # Auto-inject subagent descriptions based on allowsubagents config
            if self._agent_registry:
                subagents = self._agent_registry.get_available_subagents(agent.name)
                if subagents:
                    subagent_section = self._agent_registry.format_subagent_descriptions(subagents)
                    prompt = prompt + "\n\n" + subagent_section
            
            # Auto-inject skill descriptions (metadata layer only)
            if self._skill_loader:
                enabled_skills = self._skill_loader.get_enabled_skills()
                if enabled_skills:
                    skill_lines = ["**Skills available** (invoke with Skill tool when task matches):"]
                    for skill in enabled_skills:
                        desc = skill.description or "No description"
                        skill_lines.append(f"- {skill.name}: {desc}")
                    skill_section = "\n".join(skill_lines)
                    prompt = prompt + "\n\n" + skill_section
            
            # Load custom prompt files (GORCODE.md, AGENTS.md, CLAUDE.md)
            from ..context import load_custom_prompt
            custom_prompt = load_custom_prompt(self._get_workdir())
            if custom_prompt:
                prompt = prompt + "\n\n# 项目自定义规则\n\n" + custom_prompt
            
            return prompt
        return "You are a helpful AI assistant."
    
    def _get_workdir(self) -> str:
        """Get current working directory."""
        if self._config_manager:
            return str(self._config_manager.project_path)
        return str(os.getcwd())
    
    def process_user_input(self, user_input: str) -> Generator[Event, None, None]:
        """
        Process user input and yield events.
        
        This is the main entry point for processing user input.
        
        Args:
            user_input: User input string
            
        Yields:
            Event objects for frontend to process
        """
        # Add user message to history
        self.state.messages.append({
            "role": "user",
            "content": user_input
        })
        
        # Note: Session manager messages are synced at the end of _chat_loop
        # via set_messages() to avoid duplicate entries
        
        # Log to debug logger
        if self._debug_logger and self._debug_logger.enabled:
            self._debug_logger.log_message("user", user_input)
        
        # Emit input event
        yield Event(EventType.COMMAND_INPUT, {"input": user_input})
        
        # Check if this is a command
        if user_input.startswith("/"):
            # Command handling will be implemented in CommandHandler
            yield Event(EventType.COMMAND_OUTPUT, {"output": "Command recognized"})
            return
        
        # Process through model
        if self._model_manager is None:
            yield Event(EventType.MODEL_ERROR, {"error": "Model manager not initialized. Check configuration."})
            return
        
        current_model = self._model_manager.current()
        if current_model is None:
            available_models = self._model_manager.list_models()
            current_name = self._model_manager.current_model_name
            error_msg = f"No model connected. "
            if not available_models:
                error_msg += "No models configured. Please check ~/.gorcode/config.json"
            else:
                error_msg += f"Available models: {available_models}. Current: {current_name or 'None'}"
            yield Event(EventType.MODEL_ERROR, {"error": error_msg})
            return
        
        yield from self._chat_loop()
    
    def _chat_loop(self) -> Generator[Event, None, None]:
        """
        Execute the main chat loop using GorAI_LLMClient's chatToNextLoop.
        
        This method uses the built-in agentic loop from GorAI_LLMClient which:
        1. Calls the model
        2. Executes any tool calls
        3. Continues until no more tool calls
        
        Yields:
            Event objects for frontend to process
        """
        self.state.is_running = True
        
        # 记录对话开始前的messages长度，用于回退
        messages_count_before = len(self.state.messages)
        
        try:
            model = self._model_manager.current()
            if model is None:
                yield Event(EventType.MODEL_ERROR, {"error": "No model connected"})
                return
            
            # Get tools for current agent
            tools = []
            if self._tool_registry:
                tools = self._tool_registry.get_tool_definitions()
            
            # Log model call start
            if self._debug_logger and self._debug_logger.enabled:
                self._debug_logger.log_model_call(
                    model=self.state.current_model,
                    request={"messages": len(self.state.messages), "tools_count": len(tools)}
                )
            
            # Reset rejection flag at the start of each chat loop
            self.state.user_rejected_without_reason = False
            
            # Create tool executor that wraps our ToolRegistry with permission support
            tool_executor = GorCodeToolExecutor(
                self._tool_registry, 
                self.event_bus,
                permission_manager=self._permission_manager,
                permission_callback=self._permission_callback,
                backend_state=self.state
            )
            
            # Define interrupt check
            def interrupt_check():
                return self.state.is_interrupted
            
            # Prepare messages with system prompt
            system_prompt = self.get_system_prompt()
            messages_with_system = [{"role": "system", "content": system_prompt}] + self.state.messages
            
            # Use chatToNextLoop for the full agentic loop with reconnect handling
            while True:
                reconnect_needed = False
                for event in model.chat_to_next_loop(
                    messages=messages_with_system,
                    executor=tool_executor,
                    tools=tools,
                    interrupt_check=interrupt_check,
                ):
                    event_type = event.get("type", "")
                    
                    # Handle connection errors with retry logic
                    if self._is_connection_error_event(event):
                        # Previous reconnect attempt didn't yield any normal event
                        if self._pending_reconnect_success:
                            self._reconnect_failure_count += 1
                        self._pending_reconnect_success = False
                        reconnect_needed = True
                        should_retry = yield from self._handle_connection_error(event, messages_with_system)
                        if not should_retry:
                            return
                        break
                    
                    # Emit reconnect success message after first normal event
                    self._emit_reconnect_success_if_pending(event)
                    self._reset_reconnect_failures_on_normal_event(event)
                    
                    # Check if context compaction is needed after each tool result
                    if event_type == "tool_result":
                        # Update state.messages from messages_with_system (excluding system prompt)
                        if len(messages_with_system) > 1:
                            self.state.messages = messages_with_system[1:].copy()
                        
                        # Check and trigger auto-compaction if needed
                        if self._compaction_manager and self._compaction_manager.should_compact(self.state.messages):
                            yield from self._auto_compact_context()
                    
                    # Handle different event types
                    if event_type == "thinking":
                        # Thinking content
                        content = event.get("content", "")
                        yield Event(EventType.MODEL_THINKING, {"content": content})
                    
                    elif event_type == "answer":
                        # Answer content
                        content = event.get("content", "")
                        yield Event(EventType.MODEL_ANSWER, {
                            "content": content,
                            "agent_name": self.state.current_agent,
                        })
                    
                    elif event_type == "tool_calls":
                        # Tool calls notification (before execution)
                        tool_calls = event.get("tool_calls", [])
                        for tc in tool_calls:
                            func = tc.get("function", {})
                            tool_name = func.get("name", "unknown")
                            yield Event(EventType.MODEL_TOOL_CALL, {
                                "name": tool_name,
                                "arguments": func.get("arguments", {}),
                                "agent_name": self.state.current_agent,
                            })
                    
                    elif event_type == "tool_execution":
                        # Tool execution started
                        tool_name = event.get("tool_name", "unknown")
                        tool_call_id = event.get("tool_call_id", "")
                        args = event.get("args", {})
                        yield Event(EventType.TOOL_EXECUTION_START, {
                            "tool_name": tool_name,
                            "tool_call_id": tool_call_id,
                            "args": args,
                            "agent_name": self.state.current_agent,
                        })
                        
                        # Log tool call
                        if self._debug_logger and self._debug_logger.enabled:
                            self._debug_logger.log_tool_call(
                                tool_name=tool_name,
                                arguments=args,
                            )
                    
                    elif event_type == "tool_result":
                        # Tool execution result
                        tool_name = event.get("tool_name", "unknown")
                        tool_call_id = event.get("tool_call_id", "")
                        result = event.get("result", "")
                        
                        # Check if user rejected without reason
                        if self.state.user_rejected_without_reason:
                            # User rejected without reason - rollback and stop
                            # 回退到对话开始前的状态（只保留用户的最后一条输入）
                            self.state.messages = self.state.messages[:messages_count_before]
                            
                            # 同步session manager
                            if self._session_manager:
                                session = self._session_manager.current_session
                                if session and hasattr(session, 'messages'):
                                    session.messages = session.messages[:messages_count_before]
                            
                            # 发出用户拒绝事件通知前端
                            yield Event(EventType.USER_REJECTION, {
                                "message": "操作被用户拒绝，请提供新的指令"
                            })
                            return
                        
                        yield Event(EventType.TOOL_RESULT, {
                            "tool_name": tool_name,
                            "tool_call_id": tool_call_id,
                            "result": result,
                            "success": True,
                            "agent_name": self.state.current_agent,
                        })
                        
                        # Log tool result
                        if self._debug_logger and self._debug_logger.enabled:
                            self._debug_logger.log_tool_call(
                                tool_name=tool_name,
                                arguments={},
                                result=result[:500] if len(result) > 500 else result,
                            )
                    
                    elif event_type == "error":
                        # Error occurred
                        error_msg = event.get("message", "Unknown error")
                        yield Event(EventType.MODEL_ERROR, {"error": error_msg})
                        return
                    
                    elif event_type == "interrupted":
                        # Execution was interrupted
                        yield Event(EventType.SYSTEM_INTERRUPT, {"message": "Execution interrupted"})
                        return
                    
                    elif event_type == "end":
                        # Chat loop ended normally
                        # Messages have already been updated by chatToNextLoop
                        pass
                
                if not reconnect_needed:
                    break
            
            # Log completion
            if self._debug_logger and self._debug_logger.enabled:
                # Find the last assistant message
                for msg in reversed(self.state.messages):
                    if msg.get("role") == "assistant" and msg.get("content"):
                        self._debug_logger.log_message("assistant", msg["content"])
                        break
            
            # Sync messages from chat_to_next_loop back to state.messages
            # messages_with_system[0] is system prompt, rest are conversation
            if len(messages_with_system) > 1:
                # Replace state.messages with the updated conversation (excluding system)
                self.state.messages = messages_with_system[1:].copy()
                
                # Sync to session manager
                if self._session_manager:
                    self._session_manager.set_messages(self.state.messages)
            
        except UserRejectionError as e:
            # 用户拒绝操作且未提供理由 - 回退messages
            # 移除本轮对话中LLMClient添加的所有messages（assistant的tool_calls和tool结果）
            # 注意：messages_with_system包含system prompt，但self.state.messages不包含
            # chatToNextLoop会修改messages_with_system，但我们需要回退self.state.messages
            
            # 回退到对话开始前的状态（只保留用户的最后一条输入）
            self.state.messages = self.state.messages[:messages_count_before]
            
            # 同步session manager
            if self._session_manager:
                # 回退session中的messages
                session = self._session_manager.current_session
                if session and hasattr(session, 'messages'):
                    session.messages = session.messages[:messages_count_before]
            
            # 发出用户拒绝事件通知前端
            yield Event(EventType.USER_REJECTION, {
                "message": "操作被用户拒绝，请提供新的指令"
            })
            
        except Exception as e:
            # Log error
            if self._debug_logger and self._debug_logger.enabled:
                self._debug_logger.log_model_call(
                    model=self.state.current_model,
                    request={},
                    error=str(e)
                )
            yield Event(EventType.MODEL_ERROR, {"error": str(e)})
        finally:
            self.state.is_running = False
            yield Event(EventType.MODEL_END, {})
    
    def _execute_tools(self, tool_calls: List[Dict]) -> Generator[Event, None, None]:
        """
        Execute tool calls with permission checks.
        
        Args:
            tool_calls: List of tool calls from model
            
        Yields:
            Event objects for frontend to process
        """
        if not self._tool_registry:
            return
        
        for tool_call in tool_calls:
            try:
                tool_id = tool_call.get("id", "")
                func = tool_call.get("function", {})
                tool_name = func.get("name", "")
                arguments = json.loads(func.get("arguments", "{}"))
                
                yield Event(EventType.TOOL_EXECUTION_START, {
                    "tool_name": tool_name,
                    "tool_call_id": tool_id,
                    "args": arguments,
                    "agent_name": self.state.current_agent,
                })
                
                # Log tool call start
                if self._debug_logger and self._debug_logger.enabled:
                    self._debug_logger.log_tool_call(
                        tool_name=tool_name,
                        arguments=arguments,
                    )
                
                # Check if tool requires permission BEFORE execution
                tool = self._tool_registry.get(tool_name)
                permission_granted = True
                
                if tool and getattr(tool, 'requires_permission', False):
                    # Get metadata preview for permission check
                    # Execute tool in preview mode to get diff/metadata
                    result = self._tool_registry.execute(tool_name, **arguments)
                    
                    if result.metadata and result.metadata.get("requires_permission"):
                        # Determine permission type
                        permission_type = None
                        if tool_name == "write":
                            permission_type = PermissionType.WRITE
                        elif tool_name == "edit":
                            permission_type = PermissionType.EDIT
                        elif tool_name == "bash":
                            if result.metadata.get("has_delete"):
                                permission_type = PermissionType.BASH_DELETE
                            else:
                                permission_type = PermissionType.BASH
                        
                        if permission_type:
                            # Check if already has session permission
                            if not self._permission_manager.has_session_permission(permission_type):
                                # Need to request permission - yield permission request event
                                yield Event(EventType.PERMISSION_REQUEST, {
                                    "tool_name": tool_name,
                                    "permission_type": permission_type.value,
                                    "metadata": result.metadata,
                                })
                                
                                # Get permission response from callback (blocking)
                                if self._permission_callback:
                                    callback_result = self._permission_callback(permission_type.value, result.metadata)
                                    
                                    # Handle tuple result (response, reason)
                                    if isinstance(callback_result, tuple):
                                        response, reason = callback_result
                                    else:
                                        # Backward compatibility
                                        response = callback_result
                                        reason = None
                                    
                                    if response == "always":
                                        self._permission_manager.grant_session_permission(permission_type)
                                        permission_granted = True
                                    elif response == "once":
                                        permission_granted = True
                                    else:  # reject
                                        permission_granted = False
                                        # Store rejection reason
                                        if reason:
                                            result = ToolResult(
                                                success=False,
                                                output="",
                                                error=f"操作被用户拒绝 - {reason}"
                                            )
                                else:
                                    # No callback set - reject by default
                                    permission_granted = False
                        
                        # If permission rejected, return error
                        if not permission_granted:
                            # If we haven't set a custom error with reason, use default
                            if not (result.error and "拒绝" in result.error):
                                result = ToolResult(
                                    success=False,
                                    output="",
                                    error="操作被用户拒绝"
                                )
                        else:
                            # Permission granted - execute the actual operation
                            if tool_name in ("write", "edit"):
                                # File operations - execute with permission
                                if hasattr(tool, 'execute_with_permission'):
                                    if tool_name == "write":
                                        result = tool.execute_with_permission(
                                            file_path=result.metadata.get("file_path"),
                                            content=result.metadata.get("content"),
                                            encoding=result.metadata.get("encoding", "utf-8")
                                        )
                                    elif tool_name == "edit":
                                        result = tool.execute_with_permission(
                                            file_path=result.metadata.get("file_path"),
                                            new_content=result.metadata.get("new_content"),
                                            encoding=result.metadata.get("encoding", "utf-8")
                                        )
                            elif tool_name == "bash":
                                # Bash command - execute with permission
                                if hasattr(tool, 'execute_with_permission'):
                                    result = tool.execute_with_permission(
                                        command=result.metadata.get("command"),
                                        timeout=result.metadata.get("timeout", 60),
                                        cwd=result.metadata.get("cwd")
                                    )
                else:
                    # Tool doesn't require permission - execute directly
                    result = self._tool_registry.execute(tool_name, **arguments)
                
                # Get output for agent - include error message if present
                tool_output = result.output
                if not tool_output and result.error:
                    tool_output = f"Error: {result.error}"
                
                # Add tool result to messages
                self.state.messages.append({
                    "role": "tool",
                    "content": tool_output,
                    "tool_call_id": tool_id,
                })
                
                # Add to session manager
                if self._session_manager:
                    self._session_manager.add_message(
                        "tool", 
                        tool_output,
                        tool_name=tool_name,
                        tool_call_id=tool_id,
                    )
                
                # Log tool result
                if self._debug_logger and self._debug_logger.enabled:
                    self._debug_logger.log_tool_call(
                        tool_name=tool_name,
                        arguments=arguments,
                        result=tool_output[:500] if len(tool_output) > 500 else tool_output,
                    )
                
                yield Event(EventType.TOOL_RESULT, {
                    "tool_name": tool_name,
                    "tool_call_id": tool_id,
                    "result": tool_output,
                    "success": result.success,
                    "agent_name": self.state.current_agent,
                })
                
            except Exception as e:
                error_msg = str(e)
                
                # Log tool error
                if self._debug_logger and self._debug_logger.enabled:
                    self._debug_logger.log_tool_call(
                        tool_name=tool_name,
                        arguments=arguments,
                        error=error_msg,
                    )
                
                yield Event(EventType.TOOL_RESULT, {
                    "tool_name": tool_name,
                    "tool_call_id": tool_id,
                    "result": error_msg,
                    "success": False,
                    "agent_name": self.state.current_agent,
                })
    
    def reset_messages(self) -> None:
        """Reset message history."""
        self.state.messages = []
        
        # Clear session messages
        if self._session_manager:
            self._session_manager.clear_messages()
        
        self.emit(EventType.SESSION_NEW, {})
    
    def get_messages(self) -> List[Dict]:
        """Get current message history."""
        return self.state.messages.copy()
    
    def load_messages(self, messages: List[Dict]) -> None:
        """Load message history."""
        self.state.messages = messages.copy()
        
        # Set messages in session manager
        if self._session_manager:
            self._session_manager.set_messages(messages)
        
        self.emit(EventType.SESSION_LOAD, {"count": len(messages)})
    
    def save_current_session(self) -> bool:
        """
        Save the current session.
        
        Returns:
            True if successful
        """
        if self._session_manager:
            return self._session_manager.save_current_session()
        return False
    
    def set_debug_mode(self, enabled: bool) -> None:
        """
        Set debug mode.
        
        Args:
            enabled: Whether to enable debug mode
        """
        if self._debug_logger:
            if enabled:
                self._debug_logger.enable()
                if self._session_manager and self._session_manager.current_session:
                    session = self._session_manager.current_session
                    self._debug_logger.start_session(
                        self.state.current_agent,
                        session.session_id
                    )
            else:
                self._debug_logger.end_session()
                self._debug_logger.disable()
        
        if self._config_manager:
            self._config_manager.config.debug_mode = enabled
    
    def execute_init_command(self) -> Generator[Event, None, None]:
        """
        Execute /init command to generate GORCODE.md file.
        
        This command analyzes the project structure and generates a GORCODE.md file
        containing build commands, code style guidelines, and project architecture.
        
        Yields:
            Event objects for frontend to process
        """
        from pathlib import Path
        from ..context import get_default_prompt_file_path, get_custom_prompt_file_path
        
        project_path = self._get_workdir()
        
        # Load init prompt template
        try:
            template_path = Path(__file__).parent.parent / "context" / "init_prompt_template.txt"
            with open(template_path, "r", encoding="utf-8") as f:
                init_prompt_template = f.read()
        except Exception as e:
            yield Event(EventType.MODEL_ERROR, {"error": f"Failed to load init template: {e}"})
            return
        
        # Format template with project path
        init_prompt = init_prompt_template.format(project_path=project_path)
        
        # Check if GORCODE.md already exists
        existing_file = get_custom_prompt_file_path(project_path)
        if existing_file:
            yield Event(EventType.UI_MESSAGE, {
                "message": f"发现已存在的自定义规则文件: {existing_file.name}，将基于它进行改进"
            })
        
        # Add user message for init command
        yield Event(EventType.UI_MESSAGE, {
            "message": "正在分析项目并生成GORCODE.md..."
        })
        
        # Save original messages
        original_messages = self.state.messages.copy()
        
        # Create a temporary conversation for generating GORCODE.md
        self.state.messages = [{
            "role": "user",
            "content": init_prompt
        }]
        
        try:
            # Run the chat loop to generate content
            model = self._model_manager.current()
            if model is None:
                yield Event(EventType.MODEL_ERROR, {"error": "No model connected"})
                return
            
            # Get tools for file operations
            tools = []
            if self._tool_registry:
                tools = self._tool_registry.get_tool_definitions()
            
            # Create tool executor
            tool_executor = GorCodeToolExecutor(
                self._tool_registry,
                self.event_bus,
                permission_manager=self._permission_manager,
                permission_callback=self._permission_callback,
                backend_state=self.state
            )
            
            # Prepare system prompt
            system_prompt = self.get_system_prompt()
            messages_with_system = [{"role": "system", "content": system_prompt}] + self.state.messages
            
            # Run chat loop with reconnect handling
            generated_content = ""
            while True:
                reconnect_needed = False
                for event in model.chat_to_next_loop(
                    messages=messages_with_system,
                    executor=tool_executor,
                    tools=tools,
                    interrupt_check=lambda: self.state.is_interrupted,
                ):
                    event_type = event.get("type", "")
                    
                    if self._is_connection_error_event(event):
                        # Previous reconnect attempt didn't yield any normal event
                        if self._pending_reconnect_success:
                            self._reconnect_failure_count += 1
                        self._pending_reconnect_success = False
                        reconnect_needed = True
                        should_retry = yield from self._handle_connection_error(event, messages_with_system)
                        if not should_retry:
                            return
                        break
                    
                    # Emit reconnect success message after first normal event
                    self._emit_reconnect_success_if_pending(event)
                    
                    if event_type == "answer":
                        content = event.get("content", "")
                        generated_content += content
                        yield Event(EventType.MODEL_ANSWER, {
                            "content": content,
                            "agent_name": self.state.current_agent,
                        })
                    elif event_type == "tool_calls":
                        tool_calls = event.get("tool_calls", [])
                        for tc in tool_calls:
                            func = tc.get("function", {})
                            tool_name = func.get("name", "unknown")
                            yield Event(EventType.MODEL_TOOL_CALL, {
                                "name": tool_name,
                                "arguments": func.get("arguments", {}),
                                "agent_name": self.state.current_agent,
                            })
                    elif event_type == "tool_execution":
                        tool_name = event.get("tool_name", "unknown")
                        yield Event(EventType.TOOL_EXECUTION_START, {
                            "tool_name": tool_name,
                            "tool_call_id": event.get("tool_call_id", ""),
                            "args": event.get("args", {}),
                            "agent_name": self.state.current_agent,
                        })
                    elif event_type == "tool_result":
                        tool_name = event.get("tool_name", "unknown")
                        result = event.get("result", "")
                        yield Event(EventType.TOOL_RESULT, {
                            "tool_name": tool_name,
                            "tool_call_id": event.get("tool_call_id", ""),
                            "result": result,
                            "success": True,
                            "agent_name": self.state.current_agent,
                        })
                    elif event_type == "error":
                        error_msg = event.get("message", "Unknown error")
                        yield Event(EventType.MODEL_ERROR, {"error": error_msg})
                        return
                    elif event_type == "interrupted":
                        yield Event(EventType.SYSTEM_INTERRUPT, {"message": "Execution interrupted"})
                        return
                
                if not reconnect_needed:
                    break
            
            # Check if GORCODE.md was created by the model
            gorcode_file = get_default_prompt_file_path(project_path)
            if gorcode_file.exists():
                yield Event(EventType.UI_MESSAGE, {
                    "message": f"✓ GORCODE.md 已成功生成: {gorcode_file}"
                })
            else:
                yield Event(EventType.UI_MESSAGE, {
                    "message": "注意: 模型可能未创建GORCODE.md文件，请检查响应"
                })
            
        except Exception as e:
            yield Event(EventType.MODEL_ERROR, {"error": f"Init command failed: {e}"})
        finally:
            # Restore original messages
            self.state.messages = original_messages
            yield Event(EventType.MODEL_END, {})
