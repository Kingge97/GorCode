"""
Agent Base Classes
==================

Base classes and registry for agents.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import os
from pathlib import Path

from ..utils.serialization import dataclass_to_dict
from .capabilities import AgentCapabilityConfig


class AgentMode(Enum):
    """Agent mode types."""
    PRIMARY = "primary"    # Main agent (build, plan)
    SUBAGENT = "subagent"  # Sub-agent (explore, general)
    ALL = "all"           # Can be used as both


class PermissionLevel(Enum):
    """Permission levels for agent actions."""
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"  # Ask user for permission


@dataclass
class AgentPermission:
    """Permission configuration for an agent."""
    
    edit: PermissionLevel = PermissionLevel.ALLOW
    bash: Dict[str, PermissionLevel] = field(default_factory=lambda: {"*": PermissionLevel.ALLOW})
    skill: Dict[str, PermissionLevel] = field(default_factory=lambda: {"*": PermissionLevel.ALLOW})
    webfetch: PermissionLevel = PermissionLevel.ALLOW
    doom_loop: PermissionLevel = PermissionLevel.ASK
    external_directory: PermissionLevel = PermissionLevel.ASK
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return dataclass_to_dict(self)


@dataclass
class AgentInfo:
    """Information about an agent."""
    
    name: str
    description: str = ""
    mode: AgentMode = AgentMode.ALL
    is_native: bool = True
    is_hidden: bool = False
    is_default: bool = False
    prompt: str = ""
    tools: Dict[str, bool] = field(default_factory=dict)  # Tool permissions: {tool_name: enabled}
    allowsubagents: List[str] = field(default_factory=list)  # Allowed subagents: ["agent1", "agent2"] or ["acceptall"]/["denyall"]
    capabilities: AgentCapabilityConfig = field(default_factory=AgentCapabilityConfig)
    permissions: AgentPermission = field(default_factory=AgentPermission)
    model_config: Optional[str] = None  # Reference to model config name
    
    # Agent hierarchy
    parent: Optional[str] = None
    
    def get_full_name(self) -> str:
        """Get full hierarchical name (e.g., 'build---explore')."""
        if self.parent:
            return f"{self.parent}---{self.name}"
        return self.name
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return dataclass_to_dict(self)


class BaseAgent(ABC):
    """
    Abstract base class for all agents.
    
    All agents must inherit from this class.
    """
    
    name: str = "base_agent"
    description: str = "Base agent class"
    mode: AgentMode = AgentMode.ALL
    
    def __init__(self, config: AgentInfo = None):
        """
        Initialize agent.
        
        Args:
            config: Agent configuration
        """
        self.config = config or AgentInfo(name=self.name)
    
    @abstractmethod
    def get_system_prompt(self, context: Dict[str, Any] = None) -> str:
        """
        Get system prompt for this agent.
        
        Args:
            context: Additional context for prompt generation
            
        Returns:
            System prompt string
        """
        pass
    
    def get_available_tools(self, tool_registry: 'ToolRegistry') -> List[str]:
        """
        Get list of available tool names for this agent.
        
        Args:
            tool_registry: Tool registry to check against
            
        Returns:
            List of tool names
        """
        if not self.config.tools:
            return [tool.name for tool in tool_registry.get_all_tools()]
        
        return [
            name for name, enabled in self.config.tools.items()
            if enabled and tool_registry.get(name) is not None
        ]


class AgentRegistry:
    """
    Registry for managing available agents.
    
    Agents are loaded from:
    1. User-defined agents in .gorcode/agents/ (highest priority)
    2. Built-in agents from GorCode/agents/ (or package resources when packaged)
    """
    
    def __init__(self, workdir: Optional[str] = None):
        """
        Initialize agent registry.
        
        Args:
            workdir: Working directory for searching user-defined agents
        """
        from .loader import AgentLoader
        
        self._loader = AgentLoader()
        self._agents: Dict[str, AgentInfo] = {}
        self._workdir = workdir or os.getcwd()
        self._initialize_search_paths()
        self._load_all_agents()
    
    def _initialize_search_paths(self) -> None:
        """Initialize search paths for agents."""
        # User-defined agents (highest priority)
        user_agents_path = Path(self._workdir) / ".gorcode" / "agents"
        if user_agents_path.exists():
            self._loader.add_search_path(user_agents_path)
        
        # Also check for global user agents path
        global_user_path = Path.home() / ".gorcode" / "agents"
        if global_user_path.exists():
            self._loader.add_search_path(global_user_path)
    
    def _load_all_agents(self) -> None:
        """Load all agents from search paths."""
        agents = self._loader.load_all_agents()
        self._agents = agents
    
    def register(self, agent: AgentInfo) -> None:
        """
        Register an agent.
        
        Args:
            agent: Agent info to register
        """
        self._agents[agent.name] = agent
    
    def unregister(self, agent_name: str) -> bool:
        """
        Unregister an agent.
        
        Args:
            agent_name: Name of agent to unregister
            
        Returns:
            True if agent was unregistered, False if not found
        """
        if agent_name in self._agents:
            del self._agents[agent_name]
            return True
        return False
    
    def get(self, agent_name: str) -> Optional[AgentInfo]:
        """
        Get an agent by name.
        
        Args:
            agent_name: Name of agent to get
            
        Returns:
            Agent info or None if not found
        """
        return self._agents.get(agent_name)
    
    def get_primary_agents(self) -> List[AgentInfo]:
        """
        Get all primary agents.
        
        Returns:
            List of primary agents
        """
        return [
            agent for agent in self._agents.values()
            if agent.mode in (AgentMode.PRIMARY, AgentMode.ALL)
        ]
    
    def get_subagents(self) -> List[AgentInfo]:
        """
        Get all sub-agents.
        
        Returns:
            List of sub-agents
        """
        return [
            agent for agent in self._agents.values()
            if agent.mode in (AgentMode.SUBAGENT, AgentMode.ALL)
        ]
    
    def get_visible_agents(self) -> List[AgentInfo]:
        """
        Get all visible agents (not hidden).
        
        Returns:
            List of visible agents
        """
        return [
            agent for agent in self._agents.values()
            if not agent.is_hidden
        ]
    
    def get_default_agent(self) -> AgentInfo:
        """
        Get the default agent.
        
        Returns:
            Default agent info
        """
        for agent in self._agents.values():
            if agent.is_default:
                return agent
        return self._agents.get("build")
    
    def get_all_agents(self) -> List[AgentInfo]:
        """
        Get all registered agents.
        
        Returns:
            List of all agents
        """
        return list(self._agents.values())
    
    @property
    def agents(self) -> Dict[str, AgentInfo]:
        """Get all agents as dictionary."""
        return self._agents.copy()
    
    def reload_agent(self, agent_name: str) -> Optional[AgentInfo]:
        """
        Reload an agent from disk.
        
        Args:
            agent_name: Name of agent to reload
            
        Returns:
            Reloaded AgentInfo or None if not found
        """
        agent = self._loader.reload_agent(agent_name)
        if agent:
            self._agents[agent_name] = agent
        return agent
    
    def reload_all(self) -> Dict[str, AgentInfo]:
        """
        Reload all agents from disk.
        
        Returns:
            Dictionary of reloaded agents
        """
        self._initialize_search_paths()
        self._agents = self._loader.load_all_agents()
        return self._agents
    
    def get_available_subagents(self, agent_name: str) -> List[AgentInfo]:
        """
        Get list of subagents available to a specific agent.
        
        Based on the agent's allowsubagents configuration:
        - [] or denyall: Returns empty list
        - ["acceptall"]: Returns all SUBAGENT/ALL mode agents
        - ["explore", "general"]: Returns only specified agents
        
        Args:
            agent_name: Name of the agent to check
            
        Returns:
            List of AgentInfo for available subagents
        """
        agent = self.get(agent_name)
        if not agent:
            return []
        
        allowsubagents = agent.allowsubagents
        
        # denyall or empty list
        if not allowsubagents:
            return []
        
        # acceptall - return all subagents
        if allowsubagents == ["acceptall"]:
            return [
                a for a in self._agents.values()
                if a.mode in (AgentMode.SUBAGENT, AgentMode.ALL) 
                and a.name != agent_name  # Exclude self
                # Note: hidden agents ARE available as subagents (hidden only affects UI listing)
            ]
        
        # Specific list of allowed subagents
        result = []
        for name in allowsubagents:
            subagent = self.get(name)
            if subagent and subagent.mode in (AgentMode.SUBAGENT, AgentMode.ALL):
                result.append(subagent)
        
        return result
    
    def format_subagent_descriptions(self, subagents: List[AgentInfo]) -> str:
        """
        Format subagent descriptions for system prompt injection.
        
        Args:
            subagents: List of AgentInfo to format
            
        Returns:
            Formatted string for system prompt
        """
        if not subagents:
            return ""
        
        lines = [
            "**Subagents available** (invoke with Task tool for focused subtasks):"
        ]
        for agent in subagents:
            lines.append(f"- {agent.name}: {agent.description}")
        
        lines.extend([
            "",
            "Rules:",
            "- Use Task tool IMMEDIATELY when a task matches a subagent description",
            "- Use Task tool for subtasks needing focused exploration or implementation",
        ])
        
        return "\n".join(lines)
