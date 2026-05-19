"""
Backend Executor
===============

Main backend executor that coordinates model calls, tool execution, and agent management.
"""

from typing import Any, Dict, List, Optional, Generator, AsyncGenerator
from dataclasses import dataclass, field
import json
import sys
import os
import time
from pathlib import Path

from .events import EventBus, Event, EventType
from .model_connector import ModelConnector, ModelManager
from ..config.manager import ConfigManager, ModelConnection
from ..tools.core_tool_support.base import ToolRegistry, ToolResult
from ..agents.base import AgentRegistry, AgentInfo
from ..session import SessionManager, SessionStorage, DebugLogger
from ..permission import get_permission_manager, PermissionType, PermissionResponse
from ..sandbox import SandboxManager, protocol_error_result
from ..tools.task_tool_support.permission_exec import execute_with_permissions
from ..hooks import HookRuntime, make_call_base
from ..hooks.errors import HookExecutionError
from ..context import (
    TokenEstimator,
    TokenUsageTotals,
    CompressionAlgorithmLoader,
    CompressionController,
    CompressionError,
    ResponseCache,
    StreamingOptimizer,
    normalize_usage_payload,
    parse_compression_settings,
)
from ..skills import SkillLoader, SkillInjector
from ..context.environment import EnvironmentBlockInputs, build_environment_block
from ..platform.detector import PlatformDetector

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
                 permission_manager=None, permission_callback=None, backend_state=None,
                 sandbox_manager=None, hook_runtime: Optional[HookRuntime] = None,
                 hook_base=None):
        """
        Initialize the executor.
        
        Args:
            tool_registry: GorCode's tool registry
            event_bus: Event bus for emitting tool execution events
            permission_manager: Permission manager for session permissions
            permission_callback: Callback for permission UI
            backend_state: Backend state for setting flags
            sandbox_manager: Sandbox manager for tool boundary checks
        """
        self.tool_registry = tool_registry
        self.event_bus = event_bus
        self._permission_manager = permission_manager
        self._permission_callback = permission_callback
        self._backend_state = backend_state
        self._sandbox_manager = sandbox_manager
        self._hook_runtime = hook_runtime
        self._hook_base = hook_base
        self._user_rejected_without_reason = False  # Flag for rejection without reason
    
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

        self._sync_task_hook_context()
        before = self._run_before_tool_hook(tool_name, arguments)
        arguments = before.arguments
        early_result = self._resolve_before_tool_result(tool_name, arguments, before)
        if early_result is not None:
            return early_result

        pre_result = self._evaluate_pre_execution(tool_name, arguments)
        if pre_result:
            return self._format_after_tool_result(
                tool_name, arguments, pre_result, handled_by_sandbox=True
            )

        result = self.tool_registry.execute(tool_name, **arguments)
        return self._complete_host_tool(tool_name, arguments, result)

    def _complete_host_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: ToolResult,
    ) -> str:
        if tool_name == "Skill":
            if result.success:
                result = self._run_after_tool_hook(tool_name, arguments, result)
                return result.output
            result = self._run_after_tool_hook(tool_name, arguments, result)
            return f"Error: {result.error}" if result.error else "Error: Skill loading failed"

        tool = self.tool_registry.get(tool_name)
        result, rejected_without_reason = execute_with_permissions(
            tool_name,
            tool,
            result,
            self._permission_manager,
            self._permission_callback,
            sandbox_manager=self._sandbox_manager,
            arguments=arguments,
        )
        if rejected_without_reason:
            self._user_rejected_without_reason = True
            if self._backend_state:
                self._backend_state.user_rejected_without_reason = True

        result = self._run_after_tool_hook(tool_name, arguments, result)
        return _format_tool_result(result)

    def _resolve_before_tool_result(self, tool_name: str, arguments: Dict[str, Any], before):
        if before.action == "deny":
            result = ToolResult(False, "", before.reason or "Tool execution denied by hook")
            return self._format_after_tool_result(tool_name, arguments, result)
        if before.action != "handled" or before.tool_result is None:
            return None
        return self._format_after_tool_result(
            tool_name,
            arguments,
            before.tool_result,
            handled_by_hook=True,
        )

    def _format_after_tool_result(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: ToolResult,
        *,
        handled_by_hook: bool = False,
        handled_by_sandbox: bool = False,
    ) -> str:
        final = self._run_after_tool_hook(
            tool_name,
            arguments,
            result,
            handled_by_hook=handled_by_hook,
            handled_by_sandbox=handled_by_sandbox,
        )
        return _format_tool_result(final)

    def _run_before_tool_hook(self, tool_name: str, arguments: Dict[str, Any]):
        if not self._hook_runtime or not self._hook_base:
            from ..hooks.runtime import ToolBeforeHookResult
            return ToolBeforeHookResult(arguments=dict(arguments))
        try:
            return self._hook_runtime.before_tool_execute(
                tool_name,
                arguments,
                "",
                self._hook_base,
            )
        except Exception as exc:
            self._hook_runtime.notify_error(exc, self._hook_base, "tool.before_execute")
            raise

    def _run_after_tool_hook(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: ToolResult,
        *,
        handled_by_hook: bool = False,
        handled_by_sandbox: bool = False,
    ) -> ToolResult:
        if not self._hook_runtime or not self._hook_base:
            return result
        try:
            return self._hook_runtime.after_tool_execute(
                tool_name,
                arguments,
                result,
                self._hook_base,
                handled_by_hook=handled_by_hook,
                handled_by_sandbox=handled_by_sandbox,
            )
        except Exception as exc:
            self._hook_runtime.notify_error(exc, self._hook_base, "tool.after_execute")
            raise

    def _sync_task_hook_context(self) -> None:
        tool = self.tool_registry.get("Task") if self.tool_registry else None
        if not tool:
            return
        if hasattr(tool, "set_hook_runtime"):
            tool.set_hook_runtime(self._hook_runtime)
        if hasattr(tool, "set_hook_run_context") and self._hook_base:
            tool.set_hook_run_context(
                self._hook_base.run_id,
                self._hook_base.session_id,
                self._hook_base.model_name,
            )

    def _evaluate_pre_execution(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[ToolResult]:
        if not self._sandbox_manager:
            return None
        try:
            return self._sandbox_manager.evaluate_pre_execution(tool_name, arguments)
        except Exception as exc:
            return protocol_error_result(exc)


def _format_tool_result(result: ToolResult) -> str:
    if result.success:
        if result.metadata and "result_object" in result.metadata:
            return result.metadata.get("result_object")
        return result.output if result.output else "Command executed successfully"
    if result.error:
        return f"Error: {result.error}"
    if result.output:
        return result.output
    return "Error: Tool execution failed"


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
    session_usage: TokenUsageTotals = field(default_factory=TokenUsageTotals)
    last_request_usage: Optional[Dict[str, int]] = None
    current_run_id: Optional[str] = None
    
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
    
    def __init__(self, event_bus: EventBus = None, platform_detector: PlatformDetector = None):
        self.event_bus = event_bus or EventBus()
        self.state = BackendState()
        self._model_manager: ModelManager = None
        self._config_manager: ConfigManager = None
        self._tool_registry: ToolRegistry = None
        self._agent_registry: AgentRegistry = None
        self._session_manager: SessionManager = None
        self._debug_logger: DebugLogger = None
        self._compression_controller: Optional[CompressionController] = None
        self._response_cache: ResponseCache = None
        self._streaming_optimizer: StreamingOptimizer = None
        self._skill_loader: SkillLoader = None
        self._skill_injector: SkillInjector = None
        self._platform_detector = platform_detector or PlatformDetector()
        self._sandbox_manager: Optional[SandboxManager] = None
        self._hook_runtime: Optional[HookRuntime] = None
        
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
            self._permission_manager.apply_settings(config_manager.config)
            self._init_hook_runtime()
            self._init_sandbox_manager()
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
        # Sync permission callback to TaskTool for subagent execution
        if self._tool_registry:
            task_tool = self._tool_registry.get("Task")
            if task_tool and hasattr(task_tool, 'set_permission_callback'):
                task_tool.set_permission_callback(callback)
            if task_tool and hasattr(task_tool, 'set_permission_manager'):
                task_tool.set_permission_manager(self._permission_manager)
            if task_tool and hasattr(task_tool, 'set_sandbox_manager'):
                task_tool.set_sandbox_manager(self._sandbox_manager)

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
            self._attach_compression_to_current_model()
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

    def _sync_messages_from_system(
        self,
        messages_with_system: List[Dict],
        sync_session: bool = True,
    ) -> None:
        """Sync messages (excluding system prompt) back to state and session."""
        if len(messages_with_system) > 1:
            self.state.messages = messages_with_system[1:].copy()
            if sync_session and self._session_manager:
                self._session_manager.set_messages(self.state.messages)

    def _debug_enabled(self) -> bool:
        return bool(self._debug_logger and self._debug_logger.enabled)

    def _log_debug_message(self, role: str, content: str) -> None:
        if self._debug_enabled():
            self._debug_logger.log_message(role, content)

    def _log_debug_model_call(self, **kwargs: Any) -> None:
        if self._debug_enabled():
            self._debug_logger.log_model_call(**kwargs)

    def _log_debug_tool_call(self, **kwargs: Any) -> None:
        if self._debug_enabled():
            self._debug_logger.log_tool_call(**kwargs)

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
        tool_name: str,
        permission_type: PermissionType,
        metadata: Dict[str, Any],
    ) -> PermissionResponse:
        """
        Check if permission is granted for an operation.
        
        Args:
            permission_type: Type of permission needed
            metadata: Permission metadata
            
        Returns:
            PermissionResponse from user
        """
        decision = self._permission_manager.decide(tool_name, permission_type, metadata)
        if decision.decision == "allow":
            return PermissionResponse.ONCE
        if decision.decision == "deny":
            return PermissionResponse.REJECT

        # Emit permission request event
        self.emit(EventType.PERMISSION_REQUEST, {
            "permission_type": permission_type.value,
            "metadata": metadata,
        })

        # Request permission from user
        response = await self._permission_manager.request_permission(
            tool_name,
            permission_type,
            metadata,
        )
        
        # Emit permission response event
        self.emit(EventType.PERMISSION_RESPONSE, {
            "permission_type": permission_type.value,
            "response": response.value,
        })
        
        return response
    
    def _init_context_management(self) -> None:
        """Initialize context management (compaction, cache, streaming)."""
        self._init_compression_controller()
        
        # Initialize response cache
        self._response_cache = ResponseCache()
        
        # Initialize streaming optimizer
        self._streaming_optimizer = StreamingOptimizer()

    def _init_compression_controller(self) -> None:
        """Initialize the unified compression controller."""
        config = self._config_manager.config
        settings = parse_compression_settings(config.compression_settings)
        loader = CompressionAlgorithmLoader(
            event_bus=self.event_bus,
            model_manager=self._model_manager,
            project_path=self._config_manager.project_path,
        )
        algorithm = loader.load(settings)
        self._compression_controller = CompressionController(
            settings=settings,
            algorithm=algorithm,
            max_context_length=config.max_context_length,
        )

    def _attach_compression_to_current_model(self) -> None:
        """Attach compression hook to the current connected model."""
        if not self._compression_controller or not self._model_manager:
            return
        current_model = self._model_manager.current()
        if current_model is None:
            return
        self._compression_controller.attach_to_model(current_model)
    
    def _init_model_manager(self) -> None:
        """Initialize model manager from configuration."""
        self._model_manager = ModelManager(self.event_bus)
        
        config = self._config_manager.config
        for name, connection in config.model_connections.items():
            self._model_manager.register(connection)
        
        # Initialize TaskTool with model connector if available
        self._init_task_tool()

    def _init_sandbox_manager(self) -> None:
        """Initialize sandbox manager from configuration."""
        if not self._config_manager:
            self._sandbox_manager = None
            return
        self._sandbox_manager = SandboxManager.from_config(
            self._config_manager.config,
            self._config_manager.project_path,
        )

    def _init_hook_runtime(self) -> None:
        """Initialize GorCode application hooks from configuration."""
        if not self._config_manager:
            self._hook_runtime = None
            return
        self._hook_runtime = HookRuntime.from_raw_settings(
            self._config_manager.config.hook_settings,
            str(self._config_manager.project_path),
        )
    
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
                # 设置权限管理与回调（如果已有）
                if hasattr(task_tool, 'set_permission_manager'):
                    task_tool.set_permission_manager(self._permission_manager)
                if hasattr(task_tool, 'set_permission_callback'):
                    task_tool.set_permission_callback(self._permission_callback)
                if hasattr(task_tool, 'set_sandbox_manager'):
                    task_tool.set_sandbox_manager(self._sandbox_manager)
                if hasattr(task_tool, 'set_hook_runtime'):
                    task_tool.set_hook_runtime(self._hook_runtime)
                if hasattr(task_tool, 'set_hook_run_context'):
                    task_tool.set_hook_run_context(
                        self.state.current_run_id,
                        self._get_session_id(),
                        self.state.current_model,
                    )
                
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
            if skill_tool and hasattr(skill_tool, 'set_base_dir') and self._config_manager:
                skill_tool.set_base_dir(str(self._config_manager.project_path))
        
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

    @property
    def sandbox_manager(self) -> Optional[SandboxManager]:
        """Get sandbox manager."""
        return self._sandbox_manager

    @property
    def hook_runtime(self) -> Optional[HookRuntime]:
        """Get hook runtime."""
        return self._hook_runtime

    def get_hook_status(self) -> Dict[str, Any]:
        """Return hook status payload."""
        if not self._hook_runtime:
            self._init_hook_runtime()
        if not self._hook_runtime:
            return {"enabled": True, "hooks": [], "events": {}}
        return self._hook_runtime.status()

    def set_sandbox_enabled(self, enabled: bool) -> Dict[str, Any]:
        """Set session sandbox enablement and return status."""
        if not self._sandbox_manager:
            self._init_sandbox_manager()
        if not self._sandbox_manager:
            return {"enabled": False, "error": "Sandbox manager not available"}
        self._sandbox_manager.set_enabled(enabled)
        return self._sandbox_manager.status()

    def reload_sandbox(self) -> Dict[str, Any]:
        """Reload sandbox provider from current config."""
        if not self._config_manager:
            return {"enabled": False, "error": "Config manager not available"}
        if not self._sandbox_manager:
            self._init_sandbox_manager()
        else:
            self._config_manager._merged_config = None
            self._sandbox_manager.reload(self._config_manager.load_config())
        self._init_task_tool()
        return self.get_sandbox_status()

    def get_sandbox_status(self) -> Dict[str, Any]:
        """Return sandbox status."""
        if not self._sandbox_manager:
            self._init_sandbox_manager()
        if not self._sandbox_manager:
            return {"enabled": False, "error": "Sandbox manager not available"}
        return self._sandbox_manager.status()
    
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
    def compaction_manager(self):
        """Legacy compaction manager accessor."""
        return None

    @property
    def compression_controller(self) -> Optional[CompressionController]:
        """Get compression controller."""
        return self._compression_controller
    
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
        context_limit = self._get_context_limit()
        trigger_tokens = self._get_compression_trigger_tokens()
        usage = {
            "current_tokens": self.state.token_count,
            "current_count": self.state.token_count,
            "context_limit": context_limit,
            "usage_percentage": self._usage_percentage(self.state.token_count),
            "should_compact": self.state.token_count >= trigger_tokens,
            "should_soft_compact": self.state.token_count >= trigger_tokens,
            "should_hard_compact": self.state.token_count >= trigger_tokens,
            "soft_threshold": trigger_tokens,
            "hard_threshold": trigger_tokens,
            "compression": self._compression_status(),
        }
        self._add_session_usage_to_payload(usage)
        return usage

    def _get_context_limit(self) -> int:
        if self._config_manager:
            return int(self._config_manager.config.max_context_length)
        return 128000

    def _get_compression_trigger_tokens(self) -> int:
        if self._compression_controller:
            return self._compression_controller.trigger_tokens
        return int(self._get_context_limit() * 0.85)

    def _usage_percentage(self, token_count: int) -> float:
        context_limit = self._get_context_limit()
        if context_limit <= 0:
            return 0
        return round(token_count / context_limit * 100, 1)

    def _compression_status(self) -> Dict[str, Any]:
        if self._compression_controller:
            return self._compression_controller.status()
        return {"enabled": False}

    def _add_session_usage_to_payload(self, payload: Dict[str, Any]) -> None:
        payload.update(self.state.session_usage.to_session_payload())
        payload["last_request_usage"] = self.state.last_request_usage

    def reset_token_usage(self) -> None:
        """Reset real provider token usage for the active session."""
        self.state.session_usage = TokenUsageTotals()
        self.state.last_request_usage = None
        if self._session_manager:
            self._session_manager.clear_token_usage()

    def restore_token_usage(self, usage: Dict[str, Any]) -> None:
        """Restore real provider token usage from session metadata."""
        self.state.session_usage = TokenUsageTotals.from_dict(usage)
        self.state.last_request_usage = None

    def _record_usage_event(self, event: Dict[str, Any]) -> None:
        usage = normalize_usage_payload(event.get("usage"))
        self.state.session_usage = self.state.session_usage.add_usage(usage)
        self.state.last_request_usage = usage
        if self._session_manager:
            self._session_manager.set_token_usage(self.state.session_usage.to_dict())
    
    def check_context_overflow(self) -> bool:
        """
        Check if context is approaching overflow (soft threshold).
        
        Returns:
            True if overflow detected
        """
        return TokenEstimator.estimate_messages(self.state.messages) >= (
            self._get_compression_trigger_tokens()
        )
    
    def check_context_hard_overflow(self) -> bool:
        """
        Check if context exceeds hard threshold.
        
        Returns:
            True if hard overflow detected
        """
        return self.check_context_overflow()
    
    def compact_context(self, force: bool = False, force_soft: bool = False) -> Dict[str, Any]:
        """
        Compact the conversation context using two-phase strategy.
        
        Args:
            force: Force hard compaction even if not needed
            force_soft: Force soft compaction even if not needed
            
        Returns:
            Compaction result
        """
        if not self._compression_controller:
            return {"success": False, "error": "Compression not initialized"}
        if not self._compression_controller.settings.enabled:
            return {"success": False, "error": "Compression is disabled"}
        try:
            result = self._run_manual_compression(force, force_soft)
        except CompressionError as exc:
            return {"success": False, "error": str(exc)}
        self._apply_manual_compression_result(result)
        return self._manual_compression_payload(result)

    def _run_manual_compression(self, force: bool, force_soft: bool):
        messages = [
            {"role": "system", "content": self.get_system_prompt()},
            *self.state.messages,
        ]
        return self._compression_controller.compress_now(
            messages,
            force=True,
            source="manual",
            metadata={"force": force, "force_soft": force_soft},
        )

    def _apply_manual_compression_result(self, result) -> None:
        compressed = self._strip_leading_system(result.messages)
        self.state.messages = compressed
        self.state.token_count = result.compacted_tokens
        if self._session_manager:
            self._session_manager.set_messages(self.state.messages)
        self.emit(EventType.UI_MESSAGE, {
            "message": (
                "Context compacted: "
                f"{result.original_tokens} -> {result.compacted_tokens} tokens "
                f"({result.compression_ratio:.1f}x)"
            )
        })
        self._emit_manual_compression_summary(result)

    def _strip_leading_system(self, messages: List[Dict]) -> List[Dict]:
        if messages and messages[0].get("role") == "system":
            return [dict(message) for message in messages[1:]]
        return [dict(message) for message in messages]

    def _emit_manual_compression_summary(self, result) -> None:
        summary = result.metadata.get("summary")
        if summary:
            self.emit(EventType.UI_MESSAGE, {"message": f"[Compaction Summary] {summary}"})

    def _manual_compression_payload(self, result) -> Dict[str, Any]:
        metadata = dict(result.metadata)
        return {
            "success": True,
            "algorithm": result.algorithm,
            "original_tokens": result.original_tokens,
            "compacted_tokens": result.compacted_tokens,
            "trigger_tokens": result.trigger_tokens,
            "compression_ratio": result.compression_ratio,
            "metadata": metadata,
            "pruned_tool_results": metadata.get("pruned_tool_results", 0),
            "cleared_tool_results": metadata.get("cleared_tool_results", 0),
            "compaction_type": metadata.get("compaction_type", "none"),
            "protected_tool_calls": metadata.get("protected_tool_calls", []),
            "summary": metadata.get("summary"),
            "error": None,
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
            self._sync_current_session_agent(agent_name)
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
            self._sync_current_session_model(model_name)
            self._attach_compression_to_current_model()
            return True
        
        self.emit(EventType.UI_MESSAGE, {"message": f"Failed to connect to model: {model_name}"})
        return False

    def _sync_current_session_agent(self, agent_name: str) -> None:
        if self._session_manager:
            self._session_manager.update_agent(agent_name)

    def _sync_current_session_model(self, model_name: str) -> None:
        if self._session_manager:
            self._session_manager.update_model(model_name)
    
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

            return self._append_environment_block(prompt)
        return self._append_environment_block("You are a helpful AI assistant.")

    def _append_environment_block(self, prompt: str) -> str:
        if not prompt:
            return build_environment_block(self._collect_environment_inputs())

        block = build_environment_block(self._collect_environment_inputs())
        return prompt + "\n\n" + block

    def _collect_environment_inputs(self) -> EnvironmentBlockInputs:
        workdir = self._get_workdir()
        platform_info = self._platform_detector.detect()
        return EnvironmentBlockInputs(
            primary_workdir=workdir,
            is_git_repo=self._is_git_repo(workdir),
            additional_workdirs=self._get_additional_workdirs(),
            platform=platform_info.os_name,
            shell=platform_info.shell_type.value,
            os_version=platform_info.os_version,
        )

    def _is_git_repo(self, workdir: str) -> bool:
        return (Path(workdir) / ".git").exists()

    def _get_additional_workdirs(self) -> List[str]:
        return []
    
    def _get_workdir(self) -> str:
        """Get current working directory."""
        if self._config_manager:
            return str(self._config_manager.project_path)
        return str(os.getcwd())

    def _get_session_id(self) -> Optional[str]:
        if self._session_manager and self._session_manager.current_session:
            return self._session_manager.current_session.session_id
        return None

    def _main_hook_base(self, run_id: str):
        if not self._hook_runtime:
            self._init_hook_runtime()
        return make_call_base(
            runtime=self._hook_runtime,
            run_id=run_id,
            session_id=self._get_session_id(),
            source="main",
            agent_name=self.state.current_agent,
            model_name=self.state.current_model,
        )

    def _sync_task_hook_context(self, run_id: Optional[str]) -> None:
        if not self._tool_registry:
            return
        task_tool = self._tool_registry.get("Task")
        if not task_tool:
            return
        if hasattr(task_tool, "set_hook_runtime"):
            task_tool.set_hook_runtime(self._hook_runtime)
        if hasattr(task_tool, "set_hook_run_context"):
            task_tool.set_hook_run_context(run_id, self._get_session_id(), self.state.current_model)

    def _notify_run_error(self, error: Exception, stage: str) -> None:
        if not self._hook_runtime or not self.state.current_run_id:
            return
        self._hook_runtime.notify_error(error, self._main_hook_base(self.state.current_run_id), stage)
    
    def process_user_input(self, user_input: str) -> Generator[Event, None, None]:
        """
        Process user input and yield events.
        
        This is the main entry point for processing user input.
        
        Args:
            user_input: User input string
            
        Yields:
            Event objects for frontend to process
        """
        run_id = self._hook_runtime.new_run_id() if self._hook_runtime else f"run-{int(time.time() * 1000)}"
        self.state.current_run_id = run_id
        self._sync_task_hook_context(run_id)

        if self._hook_runtime:
            try:
                hook_result = self._hook_runtime.before_input_accept(
                    user_input,
                    self._main_hook_base(run_id),
                    "user_message",
                )
            except Exception as exc:
                self._notify_run_error(exc, "input.before_accept")
                yield Event(EventType.MODEL_ERROR, {"error": str(exc)})
                return
            if hook_result.action == "deny":
                yield Event(EventType.MODEL_ERROR, {"error": hook_result.reason or "Input denied"})
                return
            user_input = hook_result.payload.get("input", user_input)

        # Add user message to history
        self.state.messages.append({
            "role": "user",
            "content": user_input
        })
        
        # Note: Session manager messages are synced at the end of _chat_loop
        # via set_messages() to avoid duplicate entries
        
        # Log to debug logger
        self._log_debug_message("user", user_input)
        
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
            self._attach_compression_to_current_model()
            
            # Get tools for current agent
            tools = []
            if self._tool_registry:
                tools = self._tool_registry.get_tool_definitions()
            
            # Log model call start
            self._log_debug_model_call(
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
                backend_state=self.state,
                sandbox_manager=self._sandbox_manager,
                hook_runtime=self._hook_runtime,
                hook_base=self._main_hook_base(self.state.current_run_id or "") if self._hook_runtime else None,
            )
            
            # Define interrupt check
            def interrupt_check():
                return self.state.is_interrupted
            
            # Prepare messages with system prompt
            system_prompt = self.get_system_prompt()
            messages_with_system = [{"role": "system", "content": system_prompt}] + self.state.messages
            if self._hook_runtime:
                messages_with_system, tools, _ = self._hook_runtime.before_model_request(
                    messages_with_system,
                    tools,
                    self._main_hook_base(self.state.current_run_id or ""),
                )
            response_payload = {
                "answer_content": "",
                "reasoning_content": "",
                "tool_calls": [],
                "usage": None,
            }
            
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
                    
                    if event_type == "tool_result":
                        self._sync_messages_from_system(messages_with_system, sync_session=False)
                    
                    # Handle different event types
                    if event_type == "thinking":
                        # Thinking content
                        content = event.get("content", "")
                        response_payload["reasoning_content"] += content
                        yield Event(EventType.MODEL_THINKING, {"content": content})
                    
                    elif event_type == "answer":
                        # Answer content
                        content = event.get("content", "")
                        response_payload["answer_content"] += content
                        yield Event(EventType.MODEL_ANSWER, {
                            "content": content,
                            "agent_name": self.state.current_agent,
                        })

                    elif event_type == "usage":
                        response_payload["usage"] = event.get("usage")
                        self._record_usage_event(event)
                    
                    elif event_type == "tool_calls":
                        # Tool calls notification (before execution)
                        tool_calls = event.get("tool_calls", [])
                        response_payload["tool_calls"].extend(tool_calls)
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
                        self._log_debug_tool_call(
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
                        self._log_debug_tool_call(
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
            # Find the last assistant message
            for msg in reversed(self.state.messages):
                if msg.get("role") == "assistant" and msg.get("content"):
                    self._log_debug_message("assistant", msg["content"])
                    break
            
            # Sync messages from chat_to_next_loop back to state.messages
            # messages_with_system[0] is system prompt, rest are conversation
            if self._hook_runtime:
                self._hook_runtime.after_model_response(
                    response_payload,
                    self._main_hook_base(self.state.current_run_id or ""),
                )
            self._sync_messages_from_system(messages_with_system)
            
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
            self._notify_run_error(e, "chat_loop")
            # Log error
            self._log_debug_model_call(
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
                self._log_debug_tool_call(
                    tool_name=tool_name,
                    arguments=arguments,
                )
                
                tool = self._tool_registry.get(tool_name)
                result = None
                if self._sandbox_manager:
                    try:
                        result = self._sandbox_manager.evaluate_pre_execution(tool_name, arguments)
                    except Exception as exc:
                        result = protocol_error_result(exc)
                if result is None:
                    result = self._tool_registry.execute(tool_name, **arguments)
                    result, rejected_without_reason = execute_with_permissions(
                        tool_name,
                        tool,
                        result,
                        self._permission_manager,
                        self._permission_callback,
                        sandbox_manager=self._sandbox_manager,
                        arguments=arguments,
                    )
                    if rejected_without_reason:
                        self.state.user_rejected_without_reason = True
                
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
                self._log_debug_tool_call(
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
                self._log_debug_tool_call(
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
        self.reset_token_usage()
        
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
        self.reset_token_usage()
        
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
    
    def set_debug_mode(self, enabled: bool) -> Optional[str]:
        """
        Set debug mode.
        
        Args:
            enabled: Whether to enable debug mode
        """
        log_path: Optional[str] = None
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
                log_path = self._debug_logger.end_session()
                self._debug_logger.disable()
        
        if self._config_manager:
            self._config_manager.config.debug_mode = enabled

        return log_path
    
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
        if self._hook_runtime and not self.state.current_run_id:
            self.state.current_run_id = self._hook_runtime.new_run_id()
            self._sync_task_hook_context(self.state.current_run_id)
        
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
            self._attach_compression_to_current_model()
            
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
                backend_state=self.state,
                sandbox_manager=self._sandbox_manager,
                hook_runtime=self._hook_runtime,
                hook_base=self._main_hook_base(self.state.current_run_id or "") if self._hook_runtime else None,
            )
            
            # Prepare system prompt
            system_prompt = self.get_system_prompt()
            messages_with_system = [{"role": "system", "content": system_prompt}] + self.state.messages
            if self._hook_runtime:
                messages_with_system, tools, _ = self._hook_runtime.before_model_request(
                    messages_with_system,
                    tools,
                    self._main_hook_base(self.state.current_run_id or ""),
                )
            response_payload = {
                "answer_content": "",
                "reasoning_content": "",
                "tool_calls": [],
                "usage": None,
            }
            
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
                        response_payload["answer_content"] += content
                        yield Event(EventType.MODEL_ANSWER, {
                            "content": content,
                            "agent_name": self.state.current_agent,
                        })
                    elif event_type == "thinking":
                        response_payload["reasoning_content"] += event.get("content", "")
                    elif event_type == "tool_calls":
                        tool_calls = event.get("tool_calls", [])
                        response_payload["tool_calls"].extend(tool_calls)
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
                    elif event_type == "usage":
                        response_payload["usage"] = event.get("usage")
                
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
            if self._hook_runtime:
                self._hook_runtime.after_model_response(
                    response_payload,
                    self._main_hook_base(self.state.current_run_id or ""),
                )
            
        except Exception as e:
            self._notify_run_error(e, "init.generate")
            yield Event(EventType.MODEL_ERROR, {"error": f"Init command failed: {e}"})
        finally:
            # Restore original messages
            self.state.messages = original_messages
            yield Event(EventType.MODEL_END, {})
