"""
Agent Loader Module
===================

Loader for agents from Markdown files with YAML frontmatter.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    # Python 3.9+
    from importlib.resources import files, as_file
except ImportError:
    from importlib_resources import files, as_file

from .base import AgentInfo, AgentMode, AgentPermission, PermissionLevel
from ..utils.frontmatter import parse_yaml_frontmatter
from ..utils.loader_helpers import discover_files, read_text_file
from ..utils.loader_base import DiscoveredItem, LoaderBase


# Default values for Agent fields
DEFAULT_AGENT_VALUES = {
    "description": "",
    "mode": AgentMode.ALL,
    "is_native": True,
    "is_hidden": False,
    "is_default": False,
    "prompt": "",
    "tools": {},
    "allowsubagents": [],  # Default: denyall (empty list means no subagents allowed)
    "permissions": None,  # Will use AgentPermission() as default
    "model_config": None,
    "parent": None,
}


class AgentLoader(LoaderBase[AgentInfo]):
    """
    Loader for agents from Markdown files with YAML frontmatter.
    
    Agents are stored as .md files with YAML frontmatter:
    ```yaml
    ---
    name: build
    description: Full-featured agent for implementing features
    tools: Read, Write, Edit, Bash
    model: opus
    ---
    # Build Agent
    
    You are an expert coding agent...
    ```
    
    Supports loading from:
    1. User-defined agents in .gorcode/agents/ (highest priority)
    2. Built-in agents from GorCode/agents/ (development mode)
    3. Package resources (when packaged as exe)
    """
    
    AGENT_FILE_PATTERN = "*.md"
    # YAML frontmatter parsing is handled by utils.frontmatter
    
    def __init__(self, encoding: str = "utf-8"):
        """
        Initialize agent loader.
        
        Args:
            encoding: Default encoding for reading files
        """
        super().__init__(encoding=encoding)
        self._agents: Dict[str, AgentInfo] = self._items
        self._builtin_path: Optional[Path] = None
        self._builtin_loaded_from_resource = False
    
    def add_search_path(self, path: Union[str, Path]) -> None:
        """
        Add a path to search for agents.
        
        Args:
            path: Directory path to search
        """
        self._add_search_path(path, allow_redirect=False, allow_symlink=False)
    
    def _get_builtin_agents_path(self) -> Optional[Path]:
        """
        Get the path to built-in agents directory.
        
        In development mode: returns GorCode/agents/ directory
        In packaged mode: returns None (use resource loading)
        
        Returns:
            Path to built-in agents or None if using resource loading
        """
        if self._builtin_path is not None:
            return self._builtin_path
        
        # Try to find from file system (development mode)
        # loader.py is in GorCode/backend/agents/, so go up 3 levels to GorCode/, then into agents/
        dev_path = Path(__file__).parent.parent.parent / "agents"
        if dev_path.exists():
            self._builtin_path = dev_path
            self._builtin_loaded_from_resource = False
            return dev_path
        
        # Packaged mode - will use resource loading
        self._builtin_loaded_from_resource = True
        return None
    
    def _load_builtin_agent_from_resource(self, name: str) -> Optional[str]:
        """
        Load a built-in agent from package resources.
        
        This is used when the application is packaged (e.g., as exe).
        
        Args:
            name: Name of the agent (without .md extension)
            
        Returns:
            Agent file content or None if not found
        """
        try:
            # GorCode.agents is the package containing agent .md files
            agent_file = files("GorCode.agents").joinpath(f"{name}.md")
            with as_file(agent_file) as path:
                if path.exists():
                    return path.read_text(encoding=self.encoding)
        except (FileNotFoundError, TypeError, ModuleNotFoundError):
            pass
        return None
    
    def _list_builtin_agents_from_resource(self) -> List[str]:
        """
        List all built-in agents from package resources.
        
        Returns:
            List of agent names (without .md extension)
        """
        agent_names = []
        try:
            # Try to list files in the GorCode.agents package
            agents_package = files("GorCode.agents")
            # Iterate through package contents
            for item in agents_package.iterdir():
                if item.is_file() and item.name.endswith(".md"):
                    agent_names.append(item.name[:-3])  # Remove .md extension
        except (TypeError, ModuleNotFoundError, AttributeError):
            pass
        return agent_names
    
    def _discover_items(self) -> List[DiscoveredItem]:
        """
        Discover all agents in search paths and built-in location.
        """
        discovered: List[DiscoveredItem] = []
        seen_names = set()
        
        # Search in user-defined paths first
        for item in discover_files(self._search_paths, self.AGENT_FILE_PATTERN):
            agent_name = item.stem
            if agent_name not in seen_names:
                discovered.append(DiscoveredItem(name=agent_name))
                seen_names.add(agent_name)
        
        # Add built-in agents
        builtin_path = self._get_builtin_agents_path()
        if builtin_path:
            for item in builtin_path.glob(self.AGENT_FILE_PATTERN):
                if item.is_file():
                    agent_name = item.stem
                    if agent_name not in seen_names:
                        discovered.append(DiscoveredItem(name=agent_name))
                        seen_names.add(agent_name)
        else:
            # Packaged mode - get from resources
            for agent_name in self._list_builtin_agents_from_resource():
                if agent_name not in seen_names:
                    discovered.append(DiscoveredItem(name=agent_name))
                    seen_names.add(agent_name)
        
        return discovered

    def discover_agents(self) -> List[str]:
        """
        Discover all agents in search paths and built-in location.

        Returns:
            List of discovered agent names
        """
        return [item.name for item in self._discover_items()]
    
    def load_agent(self, name: str, path: Optional[Path] = None) -> Optional[AgentInfo]:
        """
        Load an agent by name.
        
        Args:
            name: Name of the agent (filename without .md extension)
            path: Optional explicit path to the agent file
            
        Returns:
            Loaded AgentInfo or None if not found
        """
        # If explicit path provided, use it
        if path:
            content = self._read_file_content(path)
            if content:
                agent_info = self._parse_agent_file(content, path.name)
                if agent_info:
                    self._agents[name] = agent_info
                    return agent_info
            return None
        
        # Search in user-defined paths first (higher priority)
        for search_path in self._search_paths:
            agent_file = search_path / f"{name}.md"
            if agent_file.exists():
                content = self._read_file_content(agent_file)
                if content:
                    agent_info = self._parse_agent_file(content, f"{name}.md")
                    if agent_info:
                        # Mark as user-defined (not native)
                        agent_info.is_native = False
                        self._agents[name] = agent_info
                        return agent_info
        
        # Then check built-in agents
        builtin_path = self._get_builtin_agents_path()
        if builtin_path:
            agent_file = builtin_path / f"{name}.md"
            if agent_file.exists():
                content = self._read_file_content(agent_file)
                if content:
                    agent_info = self._parse_agent_file(content, f"{name}.md")
                    if agent_info:
                        agent_info.is_native = True
                        self._agents[name] = agent_info
                        return agent_info
        else:
            # Packaged mode - load from resources
            content = self._load_builtin_agent_from_resource(name)
            if content:
                agent_info = self._parse_agent_file(content, f"{name}.md")
                if agent_info:
                    agent_info.is_native = True
                    self._agents[name] = agent_info
                    return agent_info
        
        return None
    
    def _read_file_content(self, path: Path) -> Optional[str]:
        """Read file content with error handling."""
        return read_text_file(path, self.encoding)
    
    def _parse_agent_file(self, content: str, filename: str) -> Optional[AgentInfo]:
        """
        Parse an agent file content.
        
        Args:
            content: Raw file content
            filename: Filename for error messages
            
        Returns:
            Parsed AgentInfo or None if parsing failed
        """
        frontmatter, remainder, has_frontmatter = parse_yaml_frontmatter(
            content,
            strip_on_error=True,
        )
        if has_frontmatter:
            prompt_content = remainder.strip()
        else:
            prompt_content = content.strip()
        
        # Extract and apply defaults
        return self._create_agent_info(frontmatter, prompt_content, filename)
    
    def _create_agent_info(
        self, 
        frontmatter: Dict[str, Any], 
        prompt: str, 
        filename: str
    ) -> AgentInfo:
        """
        Create AgentInfo from parsed frontmatter and prompt.
        
        Args:
            frontmatter: Parsed YAML frontmatter
            prompt: Markdown content (prompt text)
            filename: Original filename
            
        Returns:
            AgentInfo with defaults applied
        """
        # Get name from frontmatter or filename
        name = frontmatter.get("name") or Path(filename).stem
        
        # Parse mode
        mode_str = frontmatter.get("mode", "all").lower()
        mode = self._parse_mode(mode_str)
        
        # Parse tools
        tools = self._parse_tools(frontmatter.get("tools"))
        
        # Parse allowsubagents
        allowsubagents = self._parse_allowsubagents(frontmatter.get("allowsubagents"))
        
        # Parse permissions
        permissions = self._parse_permissions(frontmatter.get("permissions"))
        
        # Create AgentInfo with all fields
        agent_info = AgentInfo(
            name=name,
            description=frontmatter.get("description", DEFAULT_AGENT_VALUES["description"]),
            mode=mode,
            is_native=frontmatter.get("native", DEFAULT_AGENT_VALUES["is_native"]),
            is_hidden=frontmatter.get("hidden", DEFAULT_AGENT_VALUES["is_hidden"]),
            is_default=frontmatter.get("default", DEFAULT_AGENT_VALUES["is_default"]),
            prompt=prompt,
            tools=tools,
            allowsubagents=allowsubagents,
            permissions=permissions or AgentPermission(),
            model_config=frontmatter.get("model", frontmatter.get("model_config")),
            parent=frontmatter.get("parent"),
        )
        
        return agent_info
    
    def _parse_mode(self, mode_str: str) -> AgentMode:
        """Parse mode string to AgentMode enum."""
        mode_map = {
            "primary": AgentMode.PRIMARY,
            "main": AgentMode.PRIMARY,
            "subagent": AgentMode.SUBAGENT,
            "sub": AgentMode.SUBAGENT,
            "all": AgentMode.ALL,
        }
        return mode_map.get(mode_str.lower(), AgentMode.ALL)
    
    def _parse_tools(self, tools_value: Any) -> Dict[str, bool]:
        """
        Parse tools value from frontmatter.
        
        New simplified format:
        - None/empty: {} (all tools enabled - acts like acceptall)
        - "denyall": {} (deny all tools)
        - "acceptall": {"*": True} (accept all tools)
        - String: "Read, Write, Edit" -> {"Read": True, "Write": True, "Edit": True}
        - List: ["Read", "Write"] -> {"Read": True, "Write": True}
        
        Legacy format (for backward compatibility):
        - Dict: {"edit": false, "write": true} -> {"edit": False, "write": True}
        """
        if tools_value is None:
            return {}  # Empty dict means all tools enabled (acceptall behavior)
        
        # Handle special keywords
        if isinstance(tools_value, str):
            tools_str = tools_value.strip().lower()
            if tools_str == "denyall":
                return {}  # Empty dict, no tools explicitly enabled
            elif tools_str == "acceptall":
                return {"*": True}  # Special marker for accept all
            
            # Comma-separated list of tool names
            tools = []
            for item in tools_value.split(","):
                item = item.strip()
                if item:
                    tools.append(item)
            return {tool: True for tool in tools}
        
        if isinstance(tools_value, list):
            # Check for special keywords in list
            if len(tools_value) == 1:
                item = str(tools_value[0]).strip().lower()
                if item == "denyall":
                    return {}
                elif item == "acceptall":
                    return {"*": True}
            
            return {str(item): True for item in tools_value}
        
        if isinstance(tools_value, dict):
            # Legacy format: {"edit": false, "write": true}
            return {k: bool(v) for k, v in tools_value.items()}
        
        return {}
    
    def _parse_allowsubagents(self, allowsubagents_value: Any) -> List[str]:
        """
        Parse allowsubagents value from frontmatter.
        
        Format:
        - None/empty: [] (denyall - no subagents allowed, this is the default)
        - "denyall": [] (deny all subagents)
        - "acceptall": ["acceptall"] (accept all subagents)
        - String: "explore, general" -> ["explore", "general"]
        - List: ["explore", "general"] -> ["explore", "general"]
        
        Returns:
            List of allowed subagent names
        """
        if allowsubagents_value is None:
            return []  # Default: denyall (empty list)
        
        if isinstance(allowsubagents_value, str):
            value = allowsubagents_value.strip().lower()
            if value == "denyall":
                return []
            elif value == "acceptall":
                return ["acceptall"]
            
            # Comma-separated list
            subagents = []
            for item in allowsubagents_value.split(","):
                item = item.strip()
                if item:
                    subagents.append(item)
            return subagents
        
        if isinstance(allowsubagents_value, list):
            # Check for special keywords
            if len(allowsubagents_value) == 1:
                item = str(allowsubagents_value[0]).strip().lower()
                if item == "denyall":
                    return []
                elif item == "acceptall":
                    return ["acceptall"]
            
            return [str(item) for item in allowsubagents_value]
        
        return []
    
    def _parse_permissions(self, permissions_value: Any) -> Optional[AgentPermission]:
        """
        Parse permissions from frontmatter.
        
        Supports:
        - None: Returns None (will use default AgentPermission)
        - Dict with permission settings
        """
        if permissions_value is None:
            return None
        
        if not isinstance(permissions_value, dict):
            return None
        
        permission = AgentPermission()
        
        # Parse edit permission
        if "edit" in permissions_value:
            permission.edit = self._parse_permission_level(permissions_value["edit"])
        
        # Parse bash permissions
        if "bash" in permissions_value:
            bash_perms = permissions_value["bash"]
            if isinstance(bash_perms, dict):
                permission.bash = {
                    k: self._parse_permission_level(v) 
                    for k, v in bash_perms.items()
                }
        
        # Parse webfetch permission
        if "webfetch" in permissions_value:
            permission.webfetch = self._parse_permission_level(permissions_value["webfetch"])
        
        return permission
    
    def _parse_permission_level(self, value: Any) -> PermissionLevel:
        """Parse permission level from value."""
        if isinstance(value, PermissionLevel):
            return value
        
        if isinstance(value, str):
            value_lower = value.lower()
            if value_lower == "allow":
                return PermissionLevel.ALLOW
            elif value_lower == "deny":
                return PermissionLevel.DENY
            elif value_lower == "ask":
                return PermissionLevel.ASK
        
        return PermissionLevel.ALLOW
    
    def _load_item(self, name: str, path: Optional[Path]) -> Optional[AgentInfo]:
        return self.load_agent(name)

    def load_all_agents(self) -> Dict[str, AgentInfo]:
        """
        Load all discovered agents.
        
        Returns:
            Dictionary of loaded agents
        """
        return self.load_all()
    
    def get_agent(self, name: str) -> Optional[AgentInfo]:
        """Get a loaded agent by name."""
        return self.get_item(name)
    
    def get_all_agents(self) -> Dict[str, AgentInfo]:
        """Get all loaded agents."""
        return self.get_all_items()
    
    def reload_agent(self, name: str) -> Optional[AgentInfo]:
        """Reload an agent from disk."""
        return self.reload_item(name)
    
    def unload_agent(self, name: str) -> bool:
        """Unload an agent."""
        return self.unload_item(name)
