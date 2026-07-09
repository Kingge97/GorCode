from __future__ import annotations

from typing import Any


def format_capability_sections(access_policy: Any, agent_name: str) -> str:
    if not access_policy:
        return ""
    sections = []
    subagents = format_subagent_section(access_policy, agent_name)
    skills = format_skill_section(access_policy, agent_name)
    if subagents:
        sections.append(subagents)
    if skills:
        sections.append(skills)
    return "\n\n".join(sections)


def format_subagent_section(access_policy: Any, agent_name: str) -> str:
    subagents = access_policy.subagent_descriptions(agent_name)
    if not subagents:
        return ""
    lines = ["**Subagents available** (invoke with Task tool for focused subtasks):"]
    lines.extend(f"- {name}: {description}" for name, description in subagents)
    lines.extend([
        "",
        "Rules:",
        "- Use Task tool IMMEDIATELY when a task matches a subagent description",
        "- Use Task tool for subtasks needing focused exploration or implementation",
    ])
    return "\n".join(lines)


def format_skill_section(access_policy: Any, agent_name: str) -> str:
    skills = access_policy.skill_descriptions(agent_name)
    if not skills:
        return ""
    lines = ["**Skills available** (invoke with Skill tool when task matches):"]
    lines.extend(f"- {name}: {description}" for name, description in skills)
    lines.extend([
        "",
        "Rules:",
        "- Use Skill tool before specialized work that matches a listed skill",
        "- Skill tool loads full SKILL.md content only when explicitly invoked",
    ])
    return "\n".join(lines)
