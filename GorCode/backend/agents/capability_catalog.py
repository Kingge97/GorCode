from __future__ import annotations

from typing import Any

from .capabilities import (
    AgentAccessPolicy,
    AgentCatalogSnapshot,
    SkillCatalogEntry,
    SkillCatalogSnapshot,
    ToolCatalogEntry,
    ToolCatalogSnapshot,
)


def build_agent_access_policy(
    *,
    tool_registry: Any,
    skill_loader: Any,
    agent_registry: Any,
) -> AgentAccessPolicy:
    return AgentAccessPolicy(
        tools=_tool_snapshot(tool_registry),
        skills=_skill_snapshot(skill_loader),
        agents=_agent_snapshot(agent_registry),
    )


def _tool_snapshot(tool_registry: Any) -> ToolCatalogSnapshot:
    if not tool_registry:
        return ToolCatalogSnapshot(())
    return ToolCatalogSnapshot(
        tuple(
            ToolCatalogEntry(tool.name, getattr(tool, "description", ""))
            for tool in tool_registry.get_all_tools()
        )
    )


def _skill_snapshot(skill_loader: Any) -> SkillCatalogSnapshot:
    if not skill_loader:
        return SkillCatalogSnapshot(())
    return SkillCatalogSnapshot(
        tuple(
            SkillCatalogEntry(skill.name, skill.description, skill.enabled)
            for skill in skill_loader.get_all_skills().values()
        )
    )


def _agent_snapshot(agent_registry: Any) -> AgentCatalogSnapshot:
    if not agent_registry:
        return AgentCatalogSnapshot(())
    return AgentCatalogSnapshot(tuple(agent_registry.get_all_agents()))
