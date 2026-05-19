"""
Task Tool
=========

Tool for spawning and managing subagents.
"""

import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from dataclasses import dataclass

from .core_tool_support.base import BaseTool, ToolResult
from .core_tool_support.tool_utils import build_parameters_schema, tool_error_result
from ..core.events import EventBus, EventType
from ..permission import get_permission_manager
from .task_tool_support.subagent_executor import SubagentToolExecutor

if TYPE_CHECKING:
    from ..hooks.runtime import HookRuntime


@dataclass
class SubagentResult:
    """Result from a subagent execution."""
    
    agent_type: str
    description: str
    success: bool
    output: str
    tool_calls: int = 0
    duration: float = 0.0


class TaskTool(BaseTool):
    """Tool for spawning subagents to handle focused subtasks."""
    
    name = "Task"
    description = "Spawn a subagent to handle a focused subtask. Use this IMMEDIATELY when you need to explore the codebase, search for files, analyze code structure, or perform any read-only investigation. The explore subagent is faster and more efficient at exploration tasks than doing it yourself."
    category = "agent"
    needs_encoding = False
    
    # Default fallback agent types (used when agent_registry is not available)
    DEFAULT_AGENT_TYPES = {
        "explore": "Fast agent for exploring codebases, finding files, and searching code. Read-only operations.",
        "general": "General-purpose agent for researching and executing multi-step tasks.",
    }
    
    def _get_available_agent_types(self) -> Dict[str, str]:
        """
        Get available agent types from agent registry.
        
        Returns:
            Dict mapping agent name to description
        """
        if not self._agent_registry:
            return self.DEFAULT_AGENT_TYPES.copy()
        
        # Get all subagents from registry
        # Note: hidden agents ARE available (hidden only affects UI listing)
        from ..agents.base import AgentMode
        subagents = [
            agent for agent in self._agent_registry.get_all_agents()
            if agent.mode in (AgentMode.SUBAGENT, AgentMode.ALL)
        ]
        
        if not subagents:
            return self.DEFAULT_AGENT_TYPES.copy()
        
        return {agent.name: agent.description for agent in subagents}
    
    def __init__(
        self,
        default_encoding: str = "utf-8",
        model_connector=None,
        agent_registry=None,
        tool_registry=None,
        event_bus: EventBus = None,
        parent_agent_name: str = None,
        config_manager=None,
        permission_manager=None,
        permission_callback=None,
        sandbox_manager=None,
    ):
        """
        Initialize Task tool.
        
        Args:
            default_encoding: Default encoding for file operations
            model_connector: Model connector for subagent LLM calls (deprecated, use config_manager)
            agent_registry: Registry of available agents
            tool_registry: Registry of available tools
            event_bus: Event bus for emitting subagent events
            parent_agent_name: Name of the parent agent (for nested display)
            config_manager: Config manager for dynamic model selection
        """
        super().__init__(default_encoding)
        self._model_connector = model_connector
        self._agent_registry = agent_registry
        self._tool_registry = tool_registry
        self._event_bus = event_bus
        self._parent_agent_name = parent_agent_name
        self._config_manager = config_manager
        self._model_connectors: Dict[str, Any] = {}  # Cache for model connectors by agent type
        self._permission_manager = permission_manager or get_permission_manager()
        self._permission_callback = permission_callback
        self._sandbox_manager = sandbox_manager
        self._hook_runtime: Optional["HookRuntime"] = None
        self._hook_run_id: Optional[str] = None
        self._hook_session_id: Optional[str] = None
        self._hook_model_name: Optional[str] = None
        self._subagent_seq = 0  # Incremental id for subagent runs
        
    
    def set_model_connector(self, connector) -> None:
        """Set the model connector for subagent calls."""
        self._model_connector = connector
    
    def set_config_manager(self, config_manager) -> None:
        """Set the config manager for dynamic model selection."""
        self._config_manager = config_manager
    
    def _get_model_connector_for_agent(self, agent_type: str) -> Any:
        """
        Get the appropriate model connector for a subagent type.
        
        Uses agent_model_mapping configuration to determine which model to use.
        Falls back to default model_connector if config is not available.
        
        Args:
            agent_type: Type of subagent (explore, general, etc.)
            
        Returns:
            Model connector for the subagent
        """
        # Check cache first
        if agent_type in self._model_connectors:
            return self._model_connectors[agent_type]
        
        # If config_manager is available, use agent_model_mapping
        if self._config_manager:
            model_conn = self._config_manager.get_agent_model(agent_type)
            if model_conn:
                from ..core.model_connector import ModelConnector
                connector = ModelConnector(model_conn, self._event_bus)
                if connector.connect():
                    self._model_connectors[agent_type] = connector
                    return connector
        
        # Fall back to default model_connector
        return self._model_connector
    
    def set_agent_registry(self, registry) -> None:
        """Set the agent registry."""
        self._agent_registry = registry
    
    def set_tool_registry(self, registry) -> None:
        """Set the tool registry."""
        self._tool_registry = registry
    
    def set_event_bus(self, event_bus: EventBus) -> None:
        """Set the event bus for emitting events."""
        self._event_bus = event_bus
    
    def set_parent_agent_name(self, name: str) -> None:
        """Set the parent agent name for nested display."""
        self._parent_agent_name = name

    def set_permission_manager(self, manager) -> None:
        """Set the permission manager for subagent tool execution."""
        self._permission_manager = manager

    def set_permission_callback(self, callback) -> None:
        """Set the permission callback for subagent tool execution."""
        self._permission_callback = callback

    def set_sandbox_manager(self, manager) -> None:
        """Set the sandbox manager for subagent tool execution."""
        self._sandbox_manager = manager

    def set_hook_runtime(self, runtime: Optional["HookRuntime"]) -> None:
        """Set the hook runtime for subagent execution."""
        self._hook_runtime = runtime

    def set_hook_run_context(
        self,
        run_id: Optional[str],
        session_id: Optional[str],
        model_name: Optional[str],
    ) -> None:
        """Set parent run context used by subagent hooks."""
        self._hook_run_id = run_id
        self._hook_session_id = session_id
        self._hook_model_name = model_name
    
    def _next_subagent_run_id(self) -> str:
        """Generate a unique id for a subagent run."""
        self._subagent_seq += 1
        return f"subagent-{self._subagent_seq}"

    def _subagent_hook_base(
        self,
        agent_type: str,
        parent_name: Optional[str],
        subagent_run_id: str,
    ):
        if not self._hook_runtime:
            return None
        from ..hooks.runtime import make_call_base

        run_id = self._hook_run_id or self._hook_runtime.new_run_id()
        return make_call_base(
            runtime=self._hook_runtime,
            run_id=run_id,
            session_id=self._hook_session_id,
            source="subagent",
            agent_name=agent_type,
            agent_run_id=subagent_run_id,
            parent_agent=parent_name,
            subagent_type=agent_type,
            model_name=self._hook_model_name,
        )

    def _apply_subagent_input_hook(
        self,
        prompt: str,
        agent_type: str,
        parent_name: Optional[str],
        subagent_run_id: str,
    ) -> Optional[str]:
        base = self._subagent_hook_base(agent_type, parent_name, subagent_run_id)
        if not self._hook_runtime or not base:
            return prompt
        result = self._hook_runtime.before_input_accept(prompt, base, "subagent_task")
        if result.action == "deny":
            return None
        return result.payload.get("input", prompt)

    def _build_display_name(self, parent_name: Optional[str], agent_type: str) -> str:
        """Build display name with nesting path."""
        if parent_name:
            return f"{parent_name}---{agent_type}"
        return agent_type

    def _emit_event(self, event_type: EventType, data: Any = None) -> None:
        """Emit an event through the event bus."""
        if self._event_bus:
            self._event_bus.emit(event_type, data, source="subagent")

    def _emit_subagent_end(
        self,
        *,
        agent_type: str,
        success: bool,
        output: str,
        parent_name: Optional[str],
        subagent_run_id: str,
        display_name: str,
        truncate_output: bool = False,
        max_output_len: int = 300,
    ) -> None:
        """Emit a subagent end event with a consistent payload."""
        if truncate_output and output:
            output = output[:max_output_len]
        self._emit_event(EventType.AGENT_SUBAGENT_END, {
            "agent_name": agent_type,
            "success": success,
            "output": output,
            "parent_agent": parent_name,
            "agent_run_id": subagent_run_id,
            "agent_display_name": display_name,
        })
    
    def execute(
        self,
        description: str,
        prompt: str,
        agent_type: str = "explore",
        max_steps: Optional[int] = None,
    ) -> ToolResult:
        """
        Execute a subagent task.
        
        Args:
            description: Short task description (3-5 words)
            prompt: Detailed instructions for the subagent
            agent_type: Type of agent to spawn (explore, general)
            max_steps: Optional maximum number of tool calls allowed (<= 0 or None for unlimited)
            
        Returns:
            ToolResult with subagent output
        """
        # Validate agent type (dynamic from registry)
        available_types = self._get_available_agent_types()
        if agent_type not in available_types:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown agent type: {agent_type}. Valid types: {list(available_types.keys())}"
            )
        
        # Get the appropriate model connector for this agent type
        model_connector = self._get_model_connector_for_agent(agent_type)
        if model_connector is None:
            return ToolResult(
                success=False,
                output="",
                error="No model connector configured for subagent execution"
            )
        
        # 构建子代理显示名称（支持多级嵌套）
        parent_name = self._parent_agent_name
        display_name = self._build_display_name(parent_name, agent_type)
        subagent_run_id = self._next_subagent_run_id()
        prompt = self._apply_subagent_input_hook(prompt, agent_type, parent_name, subagent_run_id)
        if prompt is None:
            return ToolResult(False, "", "Subagent task denied by hook")

        # Emit subagent start event (for UI display)
        self._emit_event(EventType.AGENT_SUBAGENT_START, {
            "agent_name": agent_type,
            "description": description,
            "parent_agent": parent_name,
            "agent_run_id": subagent_run_id,
            "agent_display_name": display_name,
        })
        
        # Get agent configuration
        agent_config = None
        if self._agent_registry:
            agent_config = self._agent_registry.get(agent_type)
        
        # Build system prompt
        system_prompt = self._build_system_prompt(agent_type, agent_config)
        
        # Initialize messages for subagent
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        normalized_max_steps = self._normalize_max_steps(max_steps)
        
        # Execute subagent loop
        start_time = time.time()
        previous_parent_name = self._parent_agent_name
        self._parent_agent_name = display_name

        try:
            tool_executor = self._create_subagent_executor(
                agent_type,
                normalized_max_steps,
                subagent_run_id,
                parent_name,
            )
            loop_result = self._run_model_loop(
                messages,
                display_name,
                agent_type,
                model_connector,
                subagent_run_id,
                tool_executor,
            )

            if loop_result["error"]:
                self._emit_subagent_end(
                    agent_type=agent_type,
                    success=False,
                    output=loop_result["error"],
                    parent_name=parent_name,
                    subagent_run_id=subagent_run_id,
                    display_name=display_name,
                )
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Subagent model error: {loop_result['error']}"
                )
            
            duration = time.time() - start_time
            final_output = loop_result["output"]
            
            # 发出子代理结束事件
            self._emit_subagent_end(
                agent_type=agent_type,
                success=True,
                output=final_output or "",
                parent_name=parent_name,
                subagent_run_id=subagent_run_id,
                display_name=display_name,
                truncate_output=True,
                max_output_len=300,
            )
            
            return ToolResult(
                success=True,
                output=final_output or "(subagent completed without text output)",
                metadata={
                    "agent_type": agent_type,
                    "description": description,
                    "tool_calls": tool_executor.tool_calls,
                    "duration": duration,
                    "steps": loop_result["steps"],
                }
            )
            
        except Exception as e:
            # 发出子代理结束事件
            self._emit_subagent_end(
                agent_type=agent_type,
                success=False,
                output=str(e),
                parent_name=parent_name,
                subagent_run_id=subagent_run_id,
                display_name=display_name,
            )
            return tool_error_result(e, prefix="Subagent execution error: ")
        finally:
            self._parent_agent_name = previous_parent_name

    def _normalize_max_steps(self, max_steps: Optional[int]) -> Optional[int]:
        try:
            value = int(max_steps) if max_steps is not None else 0
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def _create_subagent_executor(
        self,
        agent_type: str,
        max_tool_calls: Optional[int],
        subagent_run_id: str,
        parent_name: Optional[str],
    ) -> SubagentToolExecutor:
        return SubagentToolExecutor(
            agent_type=agent_type,
            tool_registry=self._tool_registry,
            is_tool_allowed=self._is_tool_allowed,
            permission_manager=self._permission_manager,
            permission_callback=self._permission_callback,
            sandbox_manager=self._sandbox_manager,
            max_tool_calls=max_tool_calls,
            hook_runtime=self._hook_runtime,
            hook_base=self._subagent_hook_base(agent_type, parent_name, subagent_run_id),
        )

    def _run_model_loop(
        self,
        messages: List[Dict],
        display_name: str,
        agent_type: str,
        model_connector,
        subagent_run_id: str,
        tool_executor: SubagentToolExecutor,
    ) -> Dict[str, Any]:
        tools = self._get_allowed_tool_definitions(agent_type)
        hook_base = getattr(tool_executor, "hook_base", None)
        if self._hook_runtime and hook_base:
            messages, tools, _ = self._hook_runtime.before_model_request(
                messages,
                tools,
                hook_base,
            )
        final_output = ""
        reasoning_output = ""
        tool_calls: List[Dict[str, Any]] = []
        usage = None
        steps = 0
        for event in model_connector.chat_to_next_loop(
            messages=messages,
            executor=tool_executor,
            tools=tools,
            interrupt_check=lambda: tool_executor.limit_reached,
        ):
            event_type = event.get("type", "")
            if event_type == "answer":
                final_output += event.get("content", "")
            elif event_type == "thinking":
                reasoning_output += event.get("content", "")
            elif event_type == "tool_calls":
                tool_calls.extend(event.get("tool_calls", []))
            elif event_type == "usage":
                usage = event.get("usage")
            if event_type == "tool_result":
                steps += 1
            error = self._handle_loop_event(
                event,
                display_name,
                subagent_run_id,
                messages,
                tool_executor,
            )
            if error:
                return {"error": error, "output": final_output, "steps": steps}
        if self._hook_runtime and hook_base:
            self._hook_runtime.after_model_response(
                {
                    "answer_content": final_output,
                    "reasoning_content": reasoning_output,
                    "tool_calls": tool_calls,
                    "usage": usage,
                },
                hook_base,
            )
        return {"error": "", "output": final_output, "steps": steps}

    def _get_allowed_tool_definitions(self, agent_type: str) -> List[Dict[str, Any]]:
        if not self._tool_registry:
            return []
        definitions = self._tool_registry.get_tool_definitions()
        return [
            tool_def
            for tool_def in definitions
            if self._is_tool_allowed(agent_type, str(tool_def.get("name", "")))
        ]

    def _handle_loop_event(
        self,
        event: Dict[str, Any],
        display_name: str,
        subagent_run_id: str,
        messages: List[Dict],
        tool_executor: SubagentToolExecutor,
    ) -> str:
        event_type = event.get("type", "")
        if event_type == "answer":
            self._emit_subagent_answer(event, display_name, subagent_run_id)
        elif event_type == "tool_calls":
            self._emit_subagent_tool_calls(event, display_name, subagent_run_id)
        elif event_type == "tool_execution":
            self._emit_subagent_tool_start(event, display_name, subagent_run_id)
        elif event_type == "tool_result":
            self._emit_subagent_tool_result(event, display_name, subagent_run_id)
        return self._get_loop_error(event, tool_executor)

    def _emit_subagent_answer(
        self,
        event: Dict[str, Any],
        display_name: str,
        subagent_run_id: str,
    ) -> None:
        self._emit_event(EventType.MODEL_ANSWER, {
            "content": event.get("content", ""),
            "agent_name": display_name,
            "agent_run_id": subagent_run_id,
        })

    def _emit_subagent_tool_calls(
        self,
        event: Dict[str, Any],
        display_name: str,
        subagent_run_id: str,
    ) -> None:
        for tool_call in event.get("tool_calls", []):
            func = tool_call.get("function", {})
            self._emit_event(EventType.MODEL_TOOL_CALL, {
                "name": func.get("name", "unknown"),
                "arguments": func.get("arguments", {}),
                "agent_name": display_name,
                "agent_run_id": subagent_run_id,
            })

    def _emit_subagent_tool_start(
        self,
        event: Dict[str, Any],
        display_name: str,
        subagent_run_id: str,
    ) -> None:
        self._emit_event(EventType.TOOL_EXECUTION_START, {
            "tool_name": event.get("tool_name", "unknown"),
            "tool_call_id": event.get("tool_call_id", ""),
            "args": event.get("args", {}),
            "agent_name": display_name,
            "agent_run_id": subagent_run_id,
        })

    def _emit_subagent_tool_result(
        self,
        event: Dict[str, Any],
        display_name: str,
        subagent_run_id: str,
    ) -> None:
        self._emit_event(EventType.TOOL_RESULT, {
            "tool_name": event.get("tool_name", "unknown"),
            "tool_call_id": event.get("tool_call_id", ""),
            "result": event.get("result", ""),
            "success": True,
            "agent_name": display_name,
            "agent_run_id": subagent_run_id,
        })

    def _get_loop_error(
        self,
        event: Dict[str, Any],
        tool_executor: SubagentToolExecutor,
    ) -> str:
        event_type = event.get("type", "")
        if event_type == "error":
            return event.get("message", "Unknown model error")
        if event_type == "connection_error":
            return event.get("message", "Connection error")
        if event_type == "interrupted" and tool_executor.limit_reached:
            return f"Subagent reached max tool calls ({tool_executor.max_tool_calls})"
        if event_type == "interrupted":
            return event.get("message", "Subagent interrupted")
        return ""
    
    def _build_system_prompt(self, agent_type: str, agent_config) -> str:
        """Build system prompt for subagent."""
        base_prompt = f"You are a {agent_type} subagent."
        
        if agent_config and agent_config.prompt:
            base_prompt = agent_config.prompt
        
        return base_prompt + "\n\nComplete the task and return a clear, concise summary."
    
    def _is_tool_allowed(self, agent_type: str, tool_name: str) -> bool:
        """Check if a tool is allowed for an agent type."""
        # Try to get from agent config
        if self._agent_registry:
            agent = self._agent_registry.get(agent_type)
            if agent and agent.tools:
                # Check for acceptall marker
                if agent.tools.get("*"):
                    return True
                # Check specific tool permission
                tool_lower = tool_name.lower()
                for tool_key, enabled in agent.tools.items():
                    if tool_key.lower() == tool_lower:
                        return enabled
                # If tools are specified but this one isn't listed, deny
                return False
            # No tools config means accept all
            return True
        
        # Fallback to hardcoded rules
        if agent_type == "explore":
            allowed = ["read", "ls", "glob", "grep", "bash"]
            return tool_name.lower() in allowed
        
        if agent_type == "general":
            return True
        
        return True
    
    def get_description(self) -> str:
        """Get tool description with dynamic agent types."""
        available_types = self._get_available_agent_types()
        agent_desc = "\n".join([f"- {k}: {v}" for k, v in available_types.items()])
        return f"""Spawn a subagent for a focused subtask.

Agent types:
{agent_desc}"""

    def get_parameters(self) -> Dict[str, Any]:
        """Get tool parameter schema with dynamic agent types."""
        available_types = self._get_available_agent_types()
        agent_enum = list(available_types.keys())
        
        return build_parameters_schema(
            properties={
                "description": {
                    "type": "string",
                    "description": "Short task description (3-5 words)"
                },
                "prompt": {
                    "type": "string",
                    "description": "Detailed instructions for the subagent"
                },
                "agent_type": {
                    "type": "string",
                    "enum": agent_enum,
                    "description": "Type of agent to spawn"
                },
                "max_steps": {
                    "type": "integer",
                    "description": "Optional maximum number of tool calls (<= 0 for unlimited)",
                    "default": 0
                }
            },
            required=["description", "prompt", "agent_type"],
        )
