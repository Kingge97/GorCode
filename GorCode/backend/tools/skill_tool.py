"""
Skill Tool
==========

Tool for loading and injecting skills into the conversation.

Based on v4_skills_agent.py implementation, this tool allows the model to
load domain-specific knowledge on-demand via tool_result injection.

Key Design: Cache-Preserving Injection
--------------------------------------
Skill content is injected as tool_result (user message), NOT system prompt.
This preserves the prompt cache and avoids 20-50x cost increase.

    Wrong: Edit system prompt each time (cache invalidated)
    Right: Append skill as tool result (prefix unchanged, cache hit)

Usage:
    The model calls Skill tool when a task matches a skill description:
    - "Process this PDF" -> Skill("pdf")
    - "Build an MCP server" -> Skill("mcp-builder")
"""

from typing import Any, Dict, List, Optional
from pathlib import Path

from .base import BaseTool, ToolResult, ToolDefinition
from ..skills import SkillLoader, SkillInjector


class SkillTool(BaseTool):
    """
    Tool for loading skills to gain specialized knowledge.
    
    Skills provide domain-specific knowledge and instructions that help
    the model handle specialized tasks like PDF processing, MCP development,
    code review, etc.
    
    When to use:
    - IMMEDIATELY when user task matches a skill description
    - Before attempting domain-specific work (PDF, MCP, etc.)
    - When you need detailed instructions for a specialized task
    
    The skill content will be injected into the conversation as a tool_result,
    giving you detailed instructions and access to resources while preserving
    the prompt cache.
    """
    
    name = "Skill"
    description = """Load a skill to gain specialized knowledge for a task.

Use this tool IMMEDIATELY when:
- The user's task matches a skill description (PDF processing, MCP dev, etc.)
- You need domain-specific knowledge or best practices
- You're about to attempt specialized work you're not sure about

The skill content will be injected as a tool result, giving you detailed
instructions while preserving prompt cache efficiency."""
    category = "knowledge"
    needs_encoding = False
    
    def __init__(
        self,
        default_encoding: str = "utf-8",
        skill_loader: SkillLoader = None,
    ):
        """
        Initialize Skill tool.
        
        Args:
            default_encoding: Default encoding for file operations
            skill_loader: Skill loader instance (optional, will create if not provided)
        """
        super().__init__(default_encoding)
        self._skill_loader = skill_loader
        self._skill_injector = None
        
        if self._skill_loader:
            self._skill_injector = SkillInjector(self._skill_loader)
    
    def set_skill_loader(self, skill_loader: SkillLoader) -> None:
        """Set the skill loader and create injector."""
        self._skill_loader = skill_loader
        self._skill_injector = SkillInjector(skill_loader)
    
    def _get_available_skills(self) -> Dict[str, str]:
        """
        Get available skills with descriptions.
        
        Returns:
            Dict mapping skill name to description
        """
        if not self._skill_loader:
            return {}
        
        skills = self._skill_loader.get_all_skills()
        return {
            name: skill.description or "No description"
            for name, skill in skills.items()
            if skill.enabled
        }
    
    def _format_skill_descriptions(self) -> str:
        """Format skill descriptions for tool definition."""
        skills = self._get_available_skills()
        if not skills:
            return "(no skills available)"
        
        lines = []
        for name, description in skills.items():
            lines.append(f"- {name}: {description}")
        return "\n".join(lines)
    
    def execute(self, skill: str) -> ToolResult:
        """
        Load a skill and return its content for injection.
        
        Args:
            skill: Name of the skill to load
            
        Returns:
            ToolResult with skill content wrapped in <skill-loaded> tags
        """
        if not self._skill_loader:
            return ToolResult(
                success=False,
                output="",
                error="Skill loader not initialized"
            )
        
        # Get skill content
        skill_obj = self._skill_loader.get_skill(skill)
        if not skill_obj:
            available = ", ".join(self._skill_loader.get_all_skills().keys()) or "none"
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown skill '{skill}'. Available: {available}"
            )
        
        # Get full content with resources
        content = skill_obj.get_full_content(include_resources=True, encoding=self.default_encoding)
        
        # OpenCode-style: Add Base directory information for path resolution
        skill_dir = str(skill_obj.path)
        
        # Wrap in skill-loaded tags (like v4_skills_agent.py)
        wrapped_content = f"""<skill-loaded name="{skill}">
## Skill: {skill}

**Base directory**: {skill_dir}

{content}
</skill-loaded>

Follow the instructions in the skill above to complete the user's task.

Note: When executing commands from this skill, use the **Base directory** above to resolve relative paths. For example, if the skill references `scripts/office/soffice.py`, the full path would be `{skill_dir}/scripts/office/soffice.py`."""
        
        return ToolResult(
            success=True,
            output=wrapped_content,
            metadata={
                "skill_name": skill,
                "skill_dir": skill_dir,
                "content_length": len(wrapped_content),
                "resource_count": len(skill_obj.resources),
            }
        )
    
    def get_definition(self) -> ToolDefinition:
        """
        Get tool definition for model API.
        
        Returns:
            ToolDefinition with dynamic skill descriptions
        """
        skill_descriptions = self._format_skill_descriptions()
        
        return ToolDefinition(
            name=self.name,
            description=f"""Load a skill to gain specialized knowledge for a task.

Available skills:
{skill_descriptions}

When to use:
- IMMEDIATELY when user task matches a skill description
- Before attempting domain-specific work (PDF, MCP, etc.)
- When you need detailed instructions for specialized tasks

The skill content will be injected into the conversation, giving you
detailed instructions and access to resources.""",
            parameters={
                "type": "object",
                "properties": {
                    "skill": {
                        "type": "string",
                        "description": "Name of the skill to load",
                        "enum": list(self._get_available_skills().keys()) if self._skill_loader else []
                    }
                },
                "required": ["skill"]
            },
            category=self.category
        )
