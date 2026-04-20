"""
Skill Module
============

Skill system for GorCode - provides knowledge injection and specialized capabilities.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..utils.frontmatter import parse_yaml_frontmatter
from ..utils.loader_helpers import discover_dirs_with_file, read_text_file
from ..utils.loader_base import DiscoveredItem, LoaderBase
from ..utils.serialization import dataclass_to_dict

@dataclass
class SkillResource:
    """Resource file associated with a skill."""
    
    path: Path
    relative_path: str
    content_type: str = "text"
    
    def read_content(self, encoding: str = "utf-8") -> str:
        """Read the content of the resource file."""
        try:
            with open(self.path, "r", encoding=encoding) as f:
                return f.read()
        except Exception:
            return ""
    
    def is_binary(self) -> bool:
        """Check if the file is binary."""
        binary_extensions = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".exe", ".dll"}
        return self.path.suffix.lower() in binary_extensions


@dataclass
class Skill:
    """
    A skill that provides specialized knowledge to agents.
    
    Skills are loaded from directories containing a SKILL.md file.
    The SKILL.md file contains instructions and knowledge that will be
    injected into the conversation context.
    """
    
    name: str
    path: Path
    content: str = ""
    description: str = ""
    resources: List[SkillResource] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    
    @property
    def skill_file(self) -> Path:
        """Get the path to the SKILL.md file."""
        return self.path / "SKILL.md"
    
    def get_full_content(self, include_resources: bool = True, encoding: str = "utf-8") -> str:
        """
        Get the full content including resources.
        
        This method returns the skill content with all referenced resources
        embedded, suitable for injection into the conversation context.
        """
        parts = [self.content]
        
        if include_resources:
            for resource in self.resources:
                if not resource.is_binary():
                    resource_content = resource.read_content(encoding)
                    if resource_content:
                        parts.append(f"\n\n---\n# Resource: {resource.relative_path}\n\n{resource_content}")
        
        return "\n".join(parts)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return dataclass_to_dict(
            self,
            exclude_fields={"content", "resources"},
            extra_fields={"resource_count": lambda skill: len(skill.resources)},
        )


class SkillLoader(LoaderBase[Skill]):
    """
    Loader for skills from directories.
    
    Skills are stored in directories containing a SKILL.md file.
    The loader discovers, loads, and manages skills.
    
    Supports cross-platform skill redirection via symlink or redirect files,
    similar to .claude/skills -> ../.codex/skills pattern.
    
    SKILL.md files support YAML frontmatter for metadata:
    ---
    name: skill-name
    description: "Skill description"
    ---
    """
    
    SKILL_FILE = "SKILL.md"
    SKILL_PATTERN = re.compile(r"^#\s*(.+)$", re.MULTILINE)
    DESCRIPTION_PATTERN = re.compile(r"^#\s+.+\n+(.+?)(?:\n\n|\n#|$)", re.MULTILINE | re.DOTALL)
    # YAML frontmatter parsing is handled by utils.frontmatter
    
    def __init__(self, encoding: str = "utf-8"):
        """
        Initialize skill loader.
        
        Args:
            encoding: Default encoding for reading files
        """
        super().__init__(encoding=encoding)
        self._skills: Dict[str, Skill] = self._items
        self._skill_sources: Dict[str, Path] = {}  # Track skill source directories
    
    def add_search_path(self, path: str) -> None:
        """
        Add a path to search for skills.
        
        Supports:
        - Direct directory paths (e.g., .gorcode/skills/)
        - Redirect files containing relative path (e.g., .claude/skills -> ../.codex/skills)
        - Symlinks to directories
        
        Args:
            path: Directory path or redirect file to search
        """
        resolved = self._add_search_path(
            path,
            allow_redirect=True,
            allow_symlink=True,
        )
        if resolved:
            if resolved.resolution == "redirect":
                print(f"[SkillLoader] Resolved redirect: {resolved.source} -> {resolved.path}")
            elif resolved.resolution == "symlink":
                print(f"[SkillLoader] Resolved symlink: {resolved.source} -> {resolved.path}")
    
    def _discover_items(self) -> List[DiscoveredItem]:
        """
        Discover all skills in search paths.
        """
        discovered: List[DiscoveredItem] = []
        seen_paths = set()
        for item in discover_dirs_with_file(self._search_paths, self.SKILL_FILE):
            if item not in seen_paths:
                discovered.append(DiscoveredItem(name=item.name, path=item))
                seen_paths.add(item)
        return discovered

    def discover_skills(self) -> List[Path]:
        """
        Discover all skills in search paths.

        Returns:
            List of discovered skill directory paths
        """
        return [item.path for item in self._discover_items() if item.path]
    
    def load_skill(self, name: str, path: Optional[Path] = None) -> Optional[Skill]:
        """
        Load a skill by name.
        
        Args:
            name: Name of the skill (directory name)
            path: Optional explicit path to the skill directory
            
        Returns:
            Loaded Skill or None if not found
        """
        # Find skill path
        if path:
            skill_path = path
        else:
            skill_path = None
            # First check if we know the source from discovery
            if name in self._skill_sources:
                candidate = self._skill_sources[name] / name
                if (candidate / self.SKILL_FILE).exists():
                    skill_path = candidate
            
            # Fallback: search all paths
            if not skill_path:
                for search_path in self._search_paths:
                    candidate = search_path / name
                    if (candidate / self.SKILL_FILE).exists():
                        skill_path = candidate
                        # Remember this source
                        self._skill_sources[name] = search_path
                        break
            
            if not skill_path:
                return None
        
        # Check for SKILL.md
        skill_file = skill_path / self.SKILL_FILE
        if not skill_file.exists():
            return None
        
        try:
            # Read skill content
            raw_content = read_text_file(skill_file, self.encoding)
            if raw_content is None:
                return None
            
            # Parse YAML frontmatter if present
            frontmatter, content = self._parse_frontmatter(raw_content)
            
            # Use name from frontmatter if available, otherwise use directory name
            skill_name = frontmatter.get("name", name)
            
            # Use description from frontmatter if available, otherwise extract from content
            description = frontmatter.get("description") or self._extract_description(content)
            
            # Load resources
            resources = self._load_resources(skill_path)
            
            # Create skill
            skill = Skill(
                name=skill_name,
                path=skill_path,
                content=content,
                description=description,
                resources=resources,
                metadata={
                    "loaded_from": str(skill_path),
                    "frontmatter": frontmatter,
                },
            )
            
            self._skills[skill_name] = skill
            return skill
            
        except Exception as e:
            print(f"Error loading skill '{name}': {e}")
            return None
    
    def _parse_frontmatter(self, content: str) -> Tuple[Dict[str, Any], str]:
        """
        Parse YAML frontmatter from skill content.
        
        Args:
            content: Raw skill file content
            
        Returns:
            Tuple of (frontmatter_dict, content_without_frontmatter)
        """
        frontmatter, remaining_content, has_frontmatter = parse_yaml_frontmatter(
            content,
            strip_on_error=False,
        )
        if has_frontmatter:
            return frontmatter, remaining_content
        return {}, content
    
    def _extract_description(self, content: str) -> str:
        """Extract description from skill content."""
        # Try to find first paragraph after title
        lines = content.strip().split("\n")
        
        # Skip title line
        start_idx = 0
        if lines and lines[0].startswith("#"):
            start_idx = 1
        
        # Find first non-empty line after title
        description_lines = []
        for line in lines[start_idx:]:
            line = line.strip()
            if not line:
                if description_lines:
                    break
                continue
            if line.startswith("#"):
                break
            description_lines.append(line)
            if len(description_lines) >= 2:  # Limit description length
                break
        
        return " ".join(description_lines)[:200]
    
    def _load_resources(self, skill_path: Path) -> List[SkillResource]:
        """Load all resource files for a skill."""
        resources = []
        
        for item in skill_path.rglob("*"):
            if item.is_file() and item.name != self.SKILL_FILE:
                # Determine content type
                suffix = item.suffix.lower()
                if suffix in {".png", ".jpg", ".jpeg", ".gif"}:
                    content_type = "image"
                elif suffix in {".json", ".yaml", ".yml"}:
                    content_type = "data"
                elif suffix in {".py", ".js", ".ts", ".java", ".go", ".rs"}:
                    content_type = "code"
                else:
                    content_type = "text"
                
                resources.append(SkillResource(
                    path=item,
                    relative_path=str(item.relative_to(skill_path)),
                    content_type=content_type,
                ))
        
        return resources
    
    def _load_item(self, name: str, path: Optional[Path]) -> Optional[Skill]:
        return self.load_skill(name, path)

    def _is_loaded(self, item: DiscoveredItem) -> bool:
        if not item.path:
            return super()._is_loaded(item)
        return any(str(s.path) == str(item.path) for s in self._skills.values())

    def _get_reload_path(self, name: str) -> Optional[Path]:
        skill = self._skills.get(name)
        return skill.path if skill else None

    def _on_unload(self, name: str) -> None:
        if name in self._skill_sources:
            del self._skill_sources[name]

    def load_all_skills(self) -> Dict[str, Skill]:
        """
        Load all discovered skills.
        
        Returns:
            Dictionary of loaded skills
        """
        return self.load_all()
    
    def get_skill(self, name: str) -> Optional[Skill]:
        """
        Get a loaded skill by name.
        
        Also supports lookup by directory name for skills with frontmatter-defined names.
        
        Args:
            name: Skill name (from frontmatter) or directory name
            
        Returns:
            Skill instance or None if not found
        """
        # First try direct lookup by skill name
        if name in self._skills:
            return self._skills[name]
        
        # Fallback: search by directory name
        for skill in self._skills.values():
            if skill.path.name == name:
                return skill
        
        return None
    
    def get_all_skills(self) -> Dict[str, Skill]:
        """Get all loaded skills."""
        return self.get_all_items()
    
    def get_enabled_skills(self) -> List[Skill]:
        """Get all enabled skills."""
        return [s for s in self._skills.values() if s.enabled]
    
    def enable_skill(self, name: str) -> bool:
        """Enable a skill."""
        skill = self._skills.get(name)
        if skill:
            skill.enabled = True
            return True
        return False
    
    def disable_skill(self, name: str) -> bool:
        """Disable a skill."""
        skill = self._skills.get(name)
        if skill:
            skill.enabled = False
            return True
        return False
    
    def reload_skill(self, name: str) -> Optional[Skill]:
        """Reload a skill from disk."""
        return self.reload_item(name)
    
    def unload_skill(self, name: str) -> bool:
        """Unload a skill."""
        return self.unload_item(name)
    
    def initialize_default_paths(self, project_path: str) -> None:
        """
        Initialize default skill search paths for a project.
        
        This sets up the standard skill directories:
        - .gorcode/skills/ (project-specific, may contain redirects)
        
        Note: If you need to redirect to other directories (e.g., .claude/skills, .codex/skills),
        place a redirect file or symlink inside .gorcode/skills that points to the target directory.
        
        Args:
            project_path: Path to the project root directory
        """
        project = Path(project_path)
        
        # .gorcode/skills/ - the only standard skill directory
        # Supports redirect files and symlinks for cross-platform compatibility
        gorcode_skills = project / ".gorcode" / "skills"
        if gorcode_skills.exists():
            self.add_search_path(str(gorcode_skills))
        
        print(f"[SkillLoader] Initialized {len(self._search_paths)} skill search path(s)")
        for i, path in enumerate(self._search_paths, 1):
            print(f"  {i}. {path}")


class SkillInjector:
    """
    Injects skill content into conversation context.
    
    The injector formats skill content for injection into the conversation,
    preserving prompt cache where possible.
    """
    
    def __init__(self, skill_loader: SkillLoader):
        """
        Initialize skill injector.
        
        Args:
            skill_loader: Skill loader instance
        """
        self.skill_loader = skill_loader
    
    def inject_skills(
        self,
        skill_names: Optional[List[str]] = None,
        include_resources: bool = True,
    ) -> str:
        """
        Generate content for skill injection.
        
        Args:
            skill_names: Specific skills to inject (None for all enabled)
            include_resources: Whether to include resource files
            
        Returns:
            Formatted content for injection
        """
        if skill_names:
            skills = [
                self.skill_loader.get_skill(name)
                for name in skill_names
                if self.skill_loader.get_skill(name)
            ]
        else:
            skills = self.skill_loader.get_enabled_skills()
        
        if not skills:
            return ""
        
        parts = ["# Skills\n\nThe following skills are available for this conversation:\n"]
        
        for skill in skills:
            parts.append(f"## {skill.name}\n")
            parts.append(skill.get_full_content(include_resources=include_resources, encoding=self.skill_loader.encoding))
            parts.append("\n\n")
        
        return "".join(parts)
    
    def get_system_prompt_append(self, skill_names: Optional[List[str]] = None) -> str:
        """
        Get content to append to system prompt.
        
        This is designed to be cached as part of the system prompt
        for better token efficiency.
        
        Args:
            skill_names: Specific skills to include
            
        Returns:
            Content to append to system prompt
        """
        return self.inject_skills(skill_names, include_resources=True)
    
    def get_tool_context(self, tool_name: str, skill_names: Optional[List[str]] = None) -> str:
        """
        Get skill context relevant to a specific tool.
        
        Args:
            tool_name: Name of the tool being used
            skill_names: Specific skills to search
            
        Returns:
            Relevant context from skills
        """
        relevant_parts = []
        
        if skill_names:
            skills = [
                self.skill_loader.get_skill(name)
                for name in skill_names
                if self.skill_loader.get_skill(name)
            ]
        else:
            skills = self.skill_loader.get_enabled_skills()
        
        # Search for tool mentions in skills
        tool_pattern = re.compile(rf"\b{re.escape(tool_name)}\b", re.IGNORECASE)
        
        for skill in skills:
            if tool_pattern.search(skill.content):
                relevant_parts.append(f"From {skill.name}:\n{skill.content}")
        
        return "\n\n".join(relevant_parts)
