"""
Configuration Manager
=====================

Manages configuration for GorCode including model connections, agent settings, and user preferences.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from ..utils.serialization import dataclass_from_dict, dataclass_to_dict
import copy


@dataclass
class ModelConnection:
    """Model connection configuration."""
    
    name: str
    base_url: str
    api_key: str
    model_name: str
    router: str = "openai-chat"  # openai-chat, anthropic, minimax-anthropic, deepseek-openai
    stream: bool = True
    extra_args: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return dataclass_to_dict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelConnection":
        """Create from dictionary."""
        return dataclass_from_dict(
            cls,
            data,
            field_defaults={
                "name": "default",
                "base_url": "",
                "api_key": "",
                "model_name": "",
            },
        )


@dataclass
class GorCodeConfig:
    """Main configuration structure for GorCode."""
    
    # Default model connections
    model_connections: Dict[str, ModelConnection] = field(default_factory=dict)
    
    # Agent configuration
    default_agent: str = "build"
    agent_model_mapping: Dict[str, str] = field(default_factory=lambda: {
        "build": "main",
        "plan": "main",
        "explore": "mini",
        "general": "mini",
    })
    
    # Global settings
    default_encoding: str = "utf-8"
    debug_mode: bool = False
    max_context_length: int = 128000
    permission_diff_max_lines: int = 100
    permission_diff_page_lines: int = 100
    
    # MCP settings
    mcp_servers: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # File tool settings (optional overrides)
    file_tool_settings: Dict[str, Any] = field(default_factory=dict)

    # Permission settings (optional overrides)
    permission_settings: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return dataclass_to_dict(
            self,
            field_serializers={
                "model_connections": lambda value: {
                    name: conn.to_dict() for name, conn in (value or {}).items()
                },
            },
        )
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GorCodeConfig":
        """Create from dictionary."""
        payload = dict(data or {})
        if not payload.get("mcp_servers") and payload.get("mcpServers"):
            payload["mcp_servers"] = payload.get("mcpServers")
        if not payload.get("file_tool_settings") and payload.get("fileToolSettings"):
            payload["file_tool_settings"] = payload.get("fileToolSettings")
        if not payload.get("permission_settings") and payload.get("permissionSettings"):
            payload["permission_settings"] = payload.get("permissionSettings")

        return dataclass_from_dict(
            cls,
            payload,
            field_deserializers={
                "model_connections": lambda value: {
                    name: ModelConnection.from_dict(conn)
                    for name, conn in (value or {}).items()
                }
            },
        )


class ConfigManager:
    """
    Configuration manager for GorCode.
    
    Manages:
    - User-level configuration (~/.gorcode/config.json)
    - Project-level configuration (./.gorcode/config.json)
    - Configuration merging and priority
    """
    
    DEFAULT_CONFIG_NAME = "config.json"
    USER_CONFIG_DIR = ".gorcode"
    PROJECT_CONFIG_DIR = ".gorcode"
    
    def __init__(self, project_path: str = None, config_path: str = None):
        """
        Initialize configuration manager.
        
        Args:
            project_path: Path to project directory
            config_path: Custom configuration path (overrides default locations)
        """
        self.project_path = Path(project_path) if project_path else Path.cwd()
        self.config_path = Path(config_path) if config_path else None
        
        self._user_config: Optional[GorCodeConfig] = None
        self._project_config: Optional[GorCodeConfig] = None
        self._merged_config: Optional[GorCodeConfig] = None

    @staticmethod
    def build_default_user_config() -> GorCodeConfig:
        """Build default user configuration."""
        config = GorCodeConfig()
        config.model_connections = {
            "main": ModelConnection(
                name="main",
                base_url="https://api.openai.com/v1",
                api_key="YOUR_API_KEY_HERE",
                model_name="gpt-4",
                router="openai-chat",
                stream=True,
            ),
            "mini": ModelConnection(
                name="mini",
                base_url="https://api.openai.com/v1",
                api_key="YOUR_API_KEY_HERE",
                model_name="gpt-3.5-turbo",
                router="openai-chat",
                stream=True,
            ),
        }

        config.agent_model_mapping = {
            "build": "main",
            "plan": "main",
            "explore": "mini",
            "general": "mini",
            "compaction": "mini",
        }

        return config

    @staticmethod
    def build_default_project_config() -> GorCodeConfig:
        """Build default project configuration (minimal, inherits from user config)."""
        config = GorCodeConfig()
        config.model_connections = {}
        config.default_agent = "build"
        return config
    
    def get_user_config_dir(self) -> Path:
        """Get user configuration directory."""
        return Path.home() / self.USER_CONFIG_DIR
    
    def get_project_config_dir(self) -> Path:
        """Get project configuration directory."""
        return self.project_path / self.PROJECT_CONFIG_DIR
    
    def get_user_config_path(self) -> Path:
        """Get user configuration file path."""
        return self.get_user_config_dir() / self.DEFAULT_CONFIG_NAME
    
    def get_project_config_path(self) -> Path:
        """Get project configuration file path."""
        return self.get_project_config_dir() / self.DEFAULT_CONFIG_NAME
    
    def load_config(self) -> GorCodeConfig:
        """
        Load and merge configuration from all sources.
        
        Priority: custom_path > project > user > default
        
        Returns:
            Merged configuration
        """
        # Start with default config
        merged = GorCodeConfig()
        
        # Load user config
        user_config = self._load_user_config()
        if user_config:
            merged = self._merge_configs(merged, user_config)
        
        # Load project config
        project_config = self._load_project_config()
        if project_config:
            merged = self._merge_configs(merged, project_config)
        
        # Load custom config
        if self.config_path:
            custom_config = self._load_config_from_path(self.config_path)
            if custom_config:
                merged = self._merge_configs(merged, custom_config)
        
        self._merged_config = merged
        return merged
    
    def _load_user_config(self) -> Optional[GorCodeConfig]:
        """Load user-level configuration."""
        config_path = self.get_user_config_path()
        if config_path.exists():
            return self._load_config_from_path(config_path)
        return None
    
    def _load_project_config(self) -> Optional[GorCodeConfig]:
        """Load project-level configuration."""
        config_path = self.get_project_config_path()
        if config_path.exists():
            return self._load_config_from_path(config_path)
        return None
    
    def _load_config_from_path(self, path: Path) -> Optional[GorCodeConfig]:
        """Load configuration from a specific path."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return GorCodeConfig.from_dict(data)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading config from {path}: {e}")
            return None
    
    def _merge_configs(self, base: GorCodeConfig, override: GorCodeConfig) -> GorCodeConfig:
        """Merge two configurations, with override taking precedence."""
        result = copy.deepcopy(base)
        
        # Merge model connections
        if override.model_connections:
            if result.model_connections is None:
                result.model_connections = {}
            result.model_connections.update(override.model_connections)
        
        # Override simple values
        if override.default_agent:
            result.default_agent = override.default_agent
        if override.agent_model_mapping:
            if result.agent_model_mapping is None:
                result.agent_model_mapping = {}
            result.agent_model_mapping.update(override.agent_model_mapping)
        if override.default_encoding:
            result.default_encoding = override.default_encoding
        if override.debug_mode:
            result.debug_mode = override.debug_mode
        if override.max_context_length:
            result.max_context_length = override.max_context_length
        if override.permission_diff_max_lines:
            result.permission_diff_max_lines = override.permission_diff_max_lines
        if override.permission_diff_page_lines:
            result.permission_diff_page_lines = override.permission_diff_page_lines
        if override.mcp_servers:
            if result.mcp_servers is None:
                result.mcp_servers = {}
            result.mcp_servers.update(override.mcp_servers)
        if override.file_tool_settings:
            if result.file_tool_settings is None:
                result.file_tool_settings = {}
            result.file_tool_settings.update(override.file_tool_settings)
        if override.permission_settings:
            if result.permission_settings is None:
                result.permission_settings = {}
            result.permission_settings.update(override.permission_settings)

        return result
    
    def save_user_config(self, config: GorCodeConfig) -> bool:
        """Save configuration to user-level."""
        return self._save_config_to_path(config, self.get_user_config_path())
    
    def save_project_config(self, config: GorCodeConfig) -> bool:
        """Save configuration to project-level."""
        config_dir = self.get_project_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        return self._save_config_to_path(config, self.get_project_config_path())
    
    def _save_config_to_path(self, config: GorCodeConfig, path: Path) -> bool:
        """Save configuration to a specific path."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)
            return True
        except IOError as e:
            print(f"Error saving config to {path}: {e}")
            return False
    
    def initialize_user_config(self) -> bool:
        """Initialize user configuration directory with default config."""
        config_dir = self.get_user_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)

        default_config = self.build_default_user_config()
        return self.save_user_config(default_config)
    
    def initialize_project_config(self) -> bool:
        """Initialize project configuration directory."""
        config_dir = self.get_project_config_dir()
        
        # Create subdirectories
        (config_dir / "agents").mkdir(parents=True, exist_ok=True)
        (config_dir / "skills").mkdir(parents=True, exist_ok=True)
        
        project_config = self.build_default_project_config()
        return self.save_project_config(project_config)
    
    @property
    def config(self) -> GorCodeConfig:
        """Get current merged configuration."""
        if self._merged_config is None:
            self._merged_config = self.load_config()
        return self._merged_config
    
    def get_model_connection(self, name: str = None) -> Optional[ModelConnection]:
        """
        Get a model connection by name.
        
        Args:
            name: Connection name, or None for default (main)
            
        Returns:
            Model connection or None if not found
        """
        name = name or "main"
        return self.config.model_connections.get(name)
    
    def get_agent_model(self, agent_name: str) -> Optional[ModelConnection]:
        """
        Get the model connection for a specific agent.
        
        Args:
            agent_name: Agent name
            
        Returns:
            Model connection for the agent
        """
        mapping = self.config.agent_model_mapping
        model_name = mapping.get(agent_name, "main")
        return self.get_model_connection(model_name)
    
    def set_config_path(self, path: str) -> None:
        """
        Set a custom configuration path.
        
        This enables configuration redirection, allowing the user to specify
        a custom location for the configuration file.
        
        Args:
            path: Path to custom configuration file or directory
        """
        path = Path(path)
        if path.is_dir():
            path = path / self.DEFAULT_CONFIG_NAME
        self.config_path = path
        # Reset cached config to force reload
        self._merged_config = None
    
    def set_agent_model(self, agent_name: str, model_name: str) -> bool:
        """
        Set the model connection for a specific agent.
        
        Args:
            agent_name: Agent name
            model_name: Model connection name
            
        Returns:
            True if successful, False if model not found
        """
        if model_name not in self.config.model_connections:
            return False
        
        self.config.agent_model_mapping[agent_name] = model_name
        return True
    
    def get_agent_config(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """
        Get agent-specific configuration.
        
        Looks for agent config in:
        1. Project .gorcode/config/ subagent configs
        2. Project .gorcode/agents/ custom agent definitions
        
        Args:
            agent_name: Agent name
            
        Returns:
            Agent configuration dictionary or None
        """
        # Check for subagent config
        config_file = self.get_project_config_dir() / "config" / f"{agent_name}.json"
        if config_file.exists():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        
        # Check for custom agent definition
        agent_file = self.get_project_config_dir() / "agents" / f"{agent_name}.json"
        if agent_file.exists():
            try:
                with open(agent_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        
        return None
    
    def list_available_models(self) -> List[str]:
        """
        List all available model connection names.
        
        Returns:
            List of model connection names
        """
        return list(self.config.model_connections.keys())
    
    def add_model_connection(self, name: str, connection: ModelConnection) -> None:
        """
        Add a new model connection.
        
        Args:
            name: Connection name
            connection: Model connection configuration
        """
        self.config.model_connections[name] = connection
    
    def remove_model_connection(self, name: str) -> bool:
        """
        Remove a model connection.
        
        Args:
            name: Connection name
            
        Returns:
            True if removed, False if not found
        """
        if name in self.config.model_connections:
            del self.config.model_connections[name]
            # Update agent mappings that used this model
            for agent, model in self.config.agent_model_mapping.items():
                if model == name:
                    self.config.agent_model_mapping[agent] = "main"
            return True
        return False
    
    def save_current_config(self, location: str = "project") -> bool:
        """
        Save current configuration to specified location.
        
        Args:
            location: "user", "project", or "custom"
            
        Returns:
            True if successful
        """
        if location == "user":
            return self.save_user_config(self.config)
        elif location == "project":
            return self.save_project_config(self.config)
        elif location == "custom" and self.config_path:
            return self._save_config_to_path(self.config, self.config_path)
        return False
    
    def get_config_info(self) -> Dict[str, Any]:
        """
        Get information about configuration sources and status.
        
        Returns:
            Dictionary with config information
        """
        user_exists = self.get_user_config_path().exists()
        project_exists = self.get_project_config_path().exists()
        
        return {
            "user_config": {
                "exists": user_exists,
                "path": str(self.get_user_config_path()),
            },
            "project_config": {
                "exists": project_exists,
                "path": str(self.get_project_config_path()),
            },
            "custom_config": {
                "exists": self.config_path.exists() if self.config_path else False,
                "path": str(self.config_path) if self.config_path else None,
            },
            "merged_config": {
                "model_count": len(self.config.model_connections),
                "default_agent": self.config.default_agent,
                "agent_model_mapping": self.config.agent_model_mapping,
            },
        }

