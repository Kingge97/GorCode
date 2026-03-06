"""
Project Initializer
===================

Handles initialization of user and project configuration for GorCode.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from .manager import ConfigManager, GorCodeConfig, ModelConnection


@dataclass
class InitResult:
    """Result of initialization process."""
    
    success: bool
    message: str
    created_paths: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class ProjectInitializer:
    """
    Project initializer for GorCode.
    
    Handles:
    - User configuration directory creation (~/.gorcode)
    - Project configuration directory creation (./.gorcode)
    - Subagent configuration setup
    - Default agents and skills directories
    """
    
    USER_CONFIG_DIR = ".gorcode"
    PROJECT_CONFIG_DIR = ".gorcode"
    
    def __init__(self, project_path: str = None):
        """
        Initialize the project initializer.
        
        Args:
            project_path: Path to project directory, defaults to current directory
        """
        self.project_path = Path(project_path) if project_path else Path.cwd()
    
    def get_user_config_dir(self) -> Path:
        """Get user configuration directory path."""
        return Path.home() / self.USER_CONFIG_DIR
    
    def get_project_config_dir(self) -> Path:
        """Get project configuration directory path."""
        return self.project_path / self.PROJECT_CONFIG_DIR
    
    def initialize_user_config(self, force: bool = False) -> InitResult:
        """
        Initialize user configuration directory.
        
        Creates:
        - ~/.gorcode/
        - ~/.gorcode/config.json
        - ~/.gorcode/sessions/ (for session storage)
        
        Args:
            force: Overwrite existing configuration
            
        Returns:
            InitResult with status and details
        """
        result = InitResult(success=True, message="User configuration initialized", created_paths=[], errors=[])
        
        config_dir = self.get_user_config_dir()
        config_file = config_dir / "config.json"
        
        try:
            # Create main directory
            if not config_dir.exists():
                config_dir.mkdir(parents=True)
                result.created_paths.append(str(config_dir))
            
            # Create sessions directory
            sessions_dir = config_dir / "sessions"
            if not sessions_dir.exists():
                sessions_dir.mkdir(parents=True)
                result.created_paths.append(str(sessions_dir))
            
            # Create config file
            if not config_file.exists() or force:
                default_config = self._create_default_user_config()
                self._save_config(config_file, default_config)
                result.created_paths.append(str(config_file))
            else:
                result.message = "User configuration already exists (use force=True to overwrite)"
                
        except Exception as e:
            result.success = False
            result.errors.append(str(e))
            result.message = f"Failed to initialize user config: {e}"
        
        return result
    
    def initialize_project_config(self, force: bool = False) -> InitResult:
        """
        Initialize project configuration directory.
        
        Creates:
        - .gorcode/
        - .gorcode/config.json
        - .gorcode/agents/
        - .gorcode/skills/
        - .gorcode/config/ (for subagent configs)
        
        Args:
            force: Overwrite existing configuration
            
        Returns:
            InitResult with status and details
        """
        result = InitResult(success=True, message="Project configuration initialized", created_paths=[], errors=[])
        
        config_dir = self.get_project_config_dir()
        config_file = config_dir / "config.json"
        
        try:
            # Create main directory
            if not config_dir.exists():
                config_dir.mkdir(parents=True)
                result.created_paths.append(str(config_dir))
            
            # Create agents directory
            agents_dir = config_dir / "agents"
            if not agents_dir.exists():
                agents_dir.mkdir(parents=True)
                result.created_paths.append(str(agents_dir))
                # Create example agent file
                self._create_example_agent(agents_dir)
            
            # Create skills directory
            skills_dir = config_dir / "skills"
            if not skills_dir.exists():
                skills_dir.mkdir(parents=True)
                result.created_paths.append(str(skills_dir))
                # Create example skill file
                self._create_example_skill(skills_dir)
            
            # Create config directory for subagent configs
            config_subdir = config_dir / "config"
            if not config_subdir.exists():
                config_subdir.mkdir(parents=True)
                result.created_paths.append(str(config_subdir))
                # Create subagent config example
                self._create_subagent_config_example(config_subdir)
            
            # Create project config file
            if not config_file.exists() or force:
                project_config = self._create_default_project_config()
                self._save_config(config_file, project_config)
                result.created_paths.append(str(config_file))
            else:
                result.message = "Project configuration already exists (use force=True to overwrite)"
                
        except Exception as e:
            result.success = False
            result.errors.append(str(e))
            result.message = f"Failed to initialize project config: {e}"
        
        return result
    
    def initialize_all(self, force: bool = False) -> Dict[str, InitResult]:
        """
        Initialize both user and project configurations.
        
        Args:
            force: Overwrite existing configurations
            
        Returns:
            Dictionary with 'user' and 'project' InitResult
        """
        return {
            "user": self.initialize_user_config(force=force),
            "project": self.initialize_project_config(force=force),
        }
    
    def _create_default_user_config(self) -> GorCodeConfig:
        """Create default user configuration."""
        config = GorCodeConfig()
        
        # Default model connections
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
        
        # Agent to model mapping
        config.agent_model_mapping = {
            "build": "main",
            "plan": "main",
            "explore": "mini",
            "general": "mini",
            "compaction": "mini",
        }
        
        return config
    
    def _create_default_project_config(self) -> GorCodeConfig:
        """Create default project configuration (minimal, inherits from user config)."""
        config = GorCodeConfig()
        
        # Project-specific settings (empty to inherit from user config)
        config.model_connections = {}
        config.default_agent = "build"
        
        return config
    
    def _save_config(self, path: Path, config: GorCodeConfig) -> None:
        """Save configuration to file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)
    
    def _create_example_agent(self, agents_dir: Path) -> None:
        """Create an example agent configuration file."""
        example_agent = {
            "name": "example_agent",
            "description": "An example custom agent configuration",
            "system_prompt": "You are a helpful assistant specialized in {{specialty}}.",
            "model": "main",  # Use 'main' or 'mini' model connection
            "tools": ["read", "write", "edit", "bash"],  # Available tools
            "permissions": {
                "edit": "allow",
                "bash": {"*": "ask"},  # Ask for bash commands
            },
            "hidden": False,  # Show in agent list
        }
        
        example_path = agents_dir / "example_agent.json.example"
        with open(example_path, "w", encoding="utf-8") as f:
            json.dump(example_agent, f, indent=2, ensure_ascii=False)
    
    def _create_example_skill(self, skills_dir: Path) -> None:
        """Create an example skill file."""
        example_skill = """# Example Skill

This is an example skill file for GorCode.

## Purpose
Skills provide specialized knowledge and instructions to the agent.

## Usage
Create a SKILL.md file in the skills directory to inject knowledge into conversations.

## Template
```
# Skill Name

## Description
Brief description of what this skill does.

## Instructions
1. Step one
2. Step two
3. Step three

## Examples
Example usage of the skill.

## Notes
Additional notes or caveats.
```
"""
        
        example_path = skills_dir / "SKILL.md.example"
        with open(example_path, "w", encoding="utf-8") as f:
            f.write(example_skill)
    
    def _create_subagent_config_example(self, config_dir: Path) -> None:
        """Create example subagent configuration."""
        example_config = {
            "description": "Subagent configuration example",
            "model_connection": "mini",
            "tools": ["read", "ls", "glob", "grep"],
            "system_prompt_append": "Focus on the specific task and return concise results.",
        }
        
        example_path = config_dir / "subagent.example.json"
        with open(example_path, "w", encoding="utf-8") as f:
            json.dump(example_config, f, indent=2, ensure_ascii=False)
    
    def check_user_config_exists(self) -> bool:
        """Check if user configuration exists."""
        return (self.get_user_config_dir() / "config.json").exists()
    
    def check_project_config_exists(self) -> bool:
        """Check if project configuration exists."""
        return (self.get_project_config_dir() / "config.json").exists()
    
    def get_config_status(self) -> Dict[str, Any]:
        """Get status of all configurations."""
        return {
            "user_config": {
                "exists": self.check_user_config_exists(),
                "path": str(self.get_user_config_dir()),
            },
            "project_config": {
                "exists": self.check_project_config_exists(),
                "path": str(self.get_project_config_dir()),
            },
            "project_path": str(self.project_path),
        }
