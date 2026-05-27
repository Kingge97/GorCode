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

from typing import Any, Dict, Optional
import os
from pathlib import Path

from .core_tool_support.base import BaseTool, ToolResult
from .core_tool_support.tool_utils import build_parameters_schema
from ..skills import SkillLoader


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
    
    The skill content (SKILL.md only) will be injected into the conversation
    as a tool_result, giving you detailed instructions while preserving the
    prompt cache.
    """
    
    name = "Skill"
    description = """Load a skill to gain specialized knowledge for a task.

Use this tool IMMEDIATELY when:
- The user's task matches a skill description (PDF processing, MCP dev, etc.)
- You need domain-specific knowledge or best practices
- You're about to attempt specialized work you're not sure about

The skill content (SKILL.md only) will be injected as a tool result, giving you
detailed instructions while preserving prompt cache efficiency."""
    category = "knowledge"
    needs_encoding = False
    
    def __init__(
        self,
        default_encoding: str = "utf-8",
        skill_loader: SkillLoader = None,
        base_dir: Optional[str] = None,
    ):
        """
        Initialize Skill tool.
        
        Args:
            default_encoding: Default encoding for file operations
            skill_loader: Skill loader instance (optional, will create if not provided)
        """
        super().__init__(default_encoding)
        self._skill_loader = skill_loader
        self._base_dir = Path(base_dir).resolve() if base_dir else None
    
    def set_skill_loader(self, skill_loader: SkillLoader) -> None:
        """Set the skill loader."""
        self._skill_loader = skill_loader

    def set_base_dir(self, base_dir: Optional[str]) -> None:
        """Set the base directory for relative path display."""
        self._base_dir = Path(base_dir).resolve() if base_dir else None

    def _get_relative_skill_dir(self, skill_dir: str) -> str:
        """Return skill directory relative to base_dir when possible."""
        if not self._base_dir:
            return skill_dir
        try:
            return str(Path(skill_dir).resolve().relative_to(self._base_dir))
        except Exception:
            return os.path.relpath(Path(skill_dir).resolve(), self._base_dir)
    
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
        
        # Only load the first layer (SKILL.md content); resources are not inlined.
        content = skill_obj.get_full_content(include_resources=False, encoding=self.default_encoding)
        
        # OpenCode-style: Add Base directory information for path resolution
        skill_dir = str(skill_obj.path)
        relative_skill_dir = self._get_relative_skill_dir(skill_dir)
        
        # Wrap in skill-loaded tags (like v4_skills_agent.py)
        wrapped_content = f"""<skill-loaded name="{skill}">
**技能目录（相对主目录）**: {relative_skill_dir}
**技能目录（绝对路径）**: {skill_dir}

## Skill: {skill}

{content}
</skill-loaded>

Follow the instructions in the skill above to complete the user's task.

Note: Resources are NOT auto-loaded. If the skill references files, read them explicitly using the file tools and the skill directory above to resolve relative paths. For example, if the skill references `scripts/office/soffice.py`, the full path would be `{relative_skill_dir}/scripts/office/soffice.py` (relative to project root)."""
        
        return ToolResult(
            success=True,
            output=wrapped_content,
            metadata={
                "skill_name": skill,
                "skill_dir": skill_dir,
                "content_length": len(wrapped_content),
            }
        )
    
    def get_description(self) -> str:
        """
        Get tool description for model API with dynamic skill list.
        """
        skill_descriptions = self._format_skill_descriptions()
        return f"""Load a skill to gain specialized knowledge for a task.

Available skills:
{skill_descriptions}

When to use:
- IMMEDIATELY when user task matches a skill description
- Before attempting domain-specific work (PDF, MCP, etc.)
- When you need detailed instructions for specialized tasks

        The skill content (SKILL.md only) will be injected into the conversation,
        giving you detailed instructions."""

    def get_parameters(self) -> Dict[str, Any]:
        """Get tool parameter schema with dynamic skill options."""
        available_skills = list(self._get_available_skills().keys()) if self._skill_loader else []
        skill_schema = {
            "type": "string",
            "description": "Name of the skill to load",
        }
        if available_skills:
            skill_schema["enum"] = available_skills

        return build_parameters_schema(
            properties={
                "skill": skill_schema
            },
            required=["skill"],
        )
