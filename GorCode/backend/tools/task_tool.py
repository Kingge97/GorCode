"""
Task Tool
=========

Tool for spawning and managing subagents.
"""

import time
import json
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from .base import BaseTool, ToolResult, ToolDefinition
from ..core.events import EventBus, Event, EventType
from ..context import CompactionManager, CompactionConfig, TokenEstimator


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
        
        # Initialize compaction manager for subagent context management
        # Use config_manager settings if available, otherwise use defaults
        self._compaction_manager = self._init_compaction_manager()
    
    def _init_compaction_manager(self, model_connector=None) -> CompactionManager:
        """
        Initialize compaction manager with config from config_manager.
        
        Uses the same configuration as the main agent to ensure consistency.
        
        Args:
            model_connector: Optional model connector for summary generation
            
        Returns:
            CompactionManager instance
        """
        # Get context limit from config_manager if available
        context_limit = 128000  # Default
        if self._config_manager and hasattr(self._config_manager, 'config'):
            context_limit = getattr(self._config_manager.config, 'max_context_length', 128000)
        
        compaction_config = CompactionConfig(
            context_limit=context_limit,
            auto_compact=True,
        )
        
        # Use provided connector or fall back to default
        connector = model_connector or self._model_connector
        
        return CompactionManager(
            event_bus=self._event_bus,
            config=compaction_config,
            model_connector=connector,
        )
    
    def set_model_connector(self, connector) -> None:
        """Set the model connector for subagent calls."""
        self._model_connector = connector
        # Update compaction manager's model connector
        if self._compaction_manager:
            self._compaction_manager._model_connector = connector
    
    def set_config_manager(self, config_manager) -> None:
        """Set the config manager for dynamic model selection."""
        self._config_manager = config_manager
        # Re-initialize compaction manager with new config
        self._compaction_manager = self._init_compaction_manager()
    
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
    
    def _emit_event(self, event_type: EventType, data: Any = None) -> None:
        """Emit an event through the event bus."""
        if self._event_bus:
            self._event_bus.emit(event_type, data, source="subagent")
    
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
        
        # 构建子代理显示名称
        if self._parent_agent_name:
            display_name = f"{self._parent_agent_name}---{agent_type}"
        else:
            display_name = agent_type
        
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
        
        # Re-initialize compaction manager with the actual model connector being used
        if model_connector:
            self._compaction_manager = self._init_compaction_manager(model_connector)
        
        # Normalize max_steps: None/<=0 means unlimited
        normalized_max_steps = None
        try:
            if max_steps is not None and int(max_steps) > 0:
                normalized_max_steps = int(max_steps)
        except (TypeError, ValueError):
            normalized_max_steps = None
        
        # Execute subagent loop
        start_time = time.time()
        tool_count = 0
        final_output = ""
        last_content = ""  # 追踪上次发送的内容，避免重复
        step = 0
        
        try:
            while True:
                if normalized_max_steps is not None and step >= normalized_max_steps:
                    break
                # Call model with the appropriate connector for this agent type
                response = self._call_model(messages, display_name, model_connector)
                
                if response.is_error:
                    # 发出子代理结束事件
                    self._emit_event(EventType.AGENT_SUBAGENT_END, {
                        "agent_name": agent_type,
                        "success": False,
                        "output": response.error_message,
                        "parent_agent": self._parent_agent_name,
                    })
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Subagent model error: {response.error_message}"
                    )
                
                # Count this iteration as a step
                step += 1
                
                # Check if we have a final response (no tool calls)
                if not response.tool_calls:
                    final_output = response.content
                    break
                
                # Process tool calls
                tool_results = []
                for tool_call in response.tool_calls:
                    tool_name = tool_call.get("function", {}).get("name", "")
                    tool_args = json.loads(tool_call.get("function", {}).get("arguments", "{}"))
                    
                    # Check if tool is allowed for this agent
                    if not self._is_tool_allowed(agent_type, tool_name):
                        tool_results.append({
                            "tool_call_id": tool_call.get("id", ""),
                            "result": f"Tool '{tool_name}' is not allowed for agent type '{agent_type}'"
                        })
                        continue
                    
                    # 发出工具执行开始事件（带有代理名）
                    self._emit_event(EventType.TOOL_EXECUTION_START, {
                        "tool_name": tool_name,
                        "tool_call_id": tool_call.get("id", ""),
                        "args": tool_args,
                        "agent_name": display_name,
                    })
                    
                    # Execute tool
                    if self._tool_registry:
                        result = self._tool_registry.execute(tool_name, **tool_args)
                        tool_results.append({
                            "tool_call_id": tool_call.get("id", ""),
                            "result": result.output if result.success else f"Error: {result.error}"
                        })
                        tool_count += 1
                        
                        # 发出工具结果事件（带有代理名）
                        self._emit_event(EventType.TOOL_RESULT, {
                            "tool_name": tool_name,
                            "tool_call_id": tool_call.get("id", ""),
                            "result": result.output if result.success else f"Error: {result.error}",
                            "success": result.success,
                            "agent_name": display_name,
                        })
                
                # Add assistant message and tool results
                messages.append({"role": "assistant", "content": response.content or "", "tool_calls": response.tool_calls})
                for tr in tool_results:
                    messages.append({"role": "tool", "tool_call_id": tr["tool_call_id"], "content": tr["result"]})
                
                # Check if context compaction is needed after each tool execution
                if self._compaction_manager and self._compaction_manager.should_compact(messages):
                    # Perform auto-compaction
                    result = self._compaction_manager.compact(messages)
                    
                    if result.success and result.compaction_type != "none":
                        messages = result.messages
                        
                        # Build compaction status message
                        if result.is_hard_compaction:
                            status_msg = f"🗜️ Subagent hard compaction: {result.original_tokens} -> {result.compacted_tokens} tokens ({result.compression_ratio:.1f}x)"
                        elif result.is_soft_compaction:
                            status_msg = f"🗜️ Subagent soft compaction: {result.original_tokens} -> {result.compacted_tokens} tokens ({result.compression_ratio:.1f}x)"
                        else:
                            status_msg = f"🗜️ Subagent context compacted: {result.original_tokens} -> {result.compacted_tokens} tokens"
                        
                        # Emit compaction event for UI notification
                        self._emit_event(EventType.UI_MESSAGE, {"message": status_msg})
                        
                        # Emit compaction summary if available (full text, no truncation)
                        if result.summary:
                            summary_msg = f"[Subagent Compaction Summary] {result.summary}"
                            self._emit_event(EventType.UI_MESSAGE, {"message": summary_msg})
            
            duration = time.time() - start_time
            
            # 发出子代理结束事件
            self._emit_event(EventType.AGENT_SUBAGENT_END, {
                "agent_name": agent_type,
                "success": True,
                "output": final_output[:300] if final_output else "",
                "parent_agent": self._parent_agent_name,
            })
            
            return ToolResult(
                success=True,
                output=final_output or "(subagent completed without text output)",
                metadata={
                    "agent_type": agent_type,
                    "description": description,
                    "tool_calls": tool_count,
                    "duration": duration,
                    "steps": step,
                }
            )
            
        except Exception as e:
            # 发出子代理结束事件
            self._emit_event(EventType.AGENT_SUBAGENT_END, {
                "agent_name": agent_type,
                "success": False,
                "output": str(e),
                "parent_agent": self._parent_agent_name,
            })
            return ToolResult(
                success=False,
                output="",
                error=f"Subagent execution error: {str(e)}"
            )
    
    def _build_system_prompt(self, agent_type: str, agent_config) -> str:
        """Build system prompt for subagent."""
        base_prompt = f"You are a {agent_type} subagent."
        
        if agent_config and agent_config.prompt:
            base_prompt = agent_config.prompt
        
        return base_prompt + "\n\nComplete the task and return a clear, concise summary."
    
    def _call_model(self, messages: List[Dict], agent_name: str = None, model_connector=None) -> Any:
        """
        Call the model with messages.
        
        Args:
            messages: List of message dictionaries
            agent_name: Agent name for display (optional)
            model_connector: Model connector to use (defaults to self._model_connector)
            
        Returns:
            Response object with is_error, error_message, content, thinking, tool_calls
        """
        connector = model_connector or self._model_connector
        if not connector or not connector._model_instance:
            return type('Response', (), {
                'is_error': True,
                'error_message': 'No model available',
                'content': '',
                'tool_calls': []
            })()
        
        try:
            # Get tools for this subagent
            tools = []
            if self._tool_registry:
                tools = self._tool_registry.get_tool_definitions()
            
            # Call model and collect all responses
            full_content = ""
            full_thinking = ""
            all_tool_calls = []
            is_error = False
            error_message = ""
            
            for response in connector.chat(messages, tools):
                if response.is_error:
                    is_error = True
                    error_message = response.error_message
                    break
                
                # Accumulate content and thinking
                if response.content:
                    full_content += response.content
                    # 发送 MODEL_ANSWER 事件，让前端显示子代理发言
                    self._emit_event(EventType.MODEL_ANSWER, {
                        "content": response.content,
                        "agent_name": agent_name,
                    })
                if response.thinking:
                    full_thinking += response.thinking
                if response.tool_calls:
                    all_tool_calls.extend(response.tool_calls)
            
            # Return aggregated response
            return type('Response', (), {
                'is_error': is_error,
                'error_message': error_message,
                'content': full_content,
                'thinking': full_thinking,
                'tool_calls': all_tool_calls
            })()
            
        except Exception as e:
            return type('Response', (), {
                'is_error': True,
                'error_message': str(e),
                'content': '',
                'tool_calls': []
            })()
    
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
    
    def get_definition(self) -> ToolDefinition:
        """Get tool definition with dynamic agent types."""
        # Get available agent types dynamically
        available_types = self._get_available_agent_types()
        agent_desc = "\n".join([f"- {k}: {v}" for k, v in available_types.items()])
        agent_enum = list(available_types.keys())
        
        return ToolDefinition(
            name=self.name,
            description=f"""Spawn a subagent for a focused subtask.

Agent types:
{agent_desc}""",
            parameters={
                "type": "object",
                "properties": {
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
                "required": ["description", "prompt", "agent_type"]
            },
            category=self.category,
        )
