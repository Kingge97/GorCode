from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Tuple

RuleTuple = Tuple[str, ...]


@dataclass(frozen=True)
class NameSetRule:
    mode: str
    names: RuleTuple = ()
    explicit: bool = True

    @classmethod
    def accept_all(cls, explicit: bool = True) -> "NameSetRule":
        return cls("acceptall", (), explicit)

    @classmethod
    def deny_all(cls, explicit: bool = True) -> "NameSetRule":
        return cls("denyall", (), explicit)

    @classmethod
    def list(cls, names: Iterable[str], explicit: bool = True) -> "NameSetRule":
        return cls("list", tuple(str(name) for name in names), explicit)


@dataclass(frozen=True)
class AgentCapabilityConfig:
    tools_allow: NameSetRule = field(default_factory=lambda: NameSetRule.accept_all(False))
    tools_deny: NameSetRule = field(default_factory=lambda: NameSetRule.deny_all(False))
    skills_allow: NameSetRule = field(default_factory=lambda: NameSetRule.accept_all(False))
    skills_deny: NameSetRule = field(default_factory=lambda: NameSetRule.deny_all(False))
    subagents_allow: NameSetRule = field(default_factory=lambda: NameSetRule.deny_all(False))


@dataclass(frozen=True)
class ToolCatalogEntry:
    name: str
    description: str = ""


@dataclass(frozen=True)
class SkillCatalogEntry:
    name: str
    description: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class AgentCatalogEntry:
    name: str
    description: str = ""
    mode: Any = "all"


@dataclass(frozen=True)
class ToolCatalogSnapshot:
    tools: Tuple[ToolCatalogEntry, ...]


@dataclass(frozen=True)
class SkillCatalogSnapshot:
    skills: Tuple[SkillCatalogEntry, ...]


@dataclass(frozen=True)
class AgentCatalogSnapshot:
    agents: Tuple[Any, ...]


class AgentAccessPolicy:
    def __init__(
        self,
        *,
        tools: ToolCatalogSnapshot,
        skills: SkillCatalogSnapshot,
        agents: AgentCatalogSnapshot,
    ) -> None:
        self._tools = tools
        self._skills = skills
        self._agents = agents
        self._tool_by_lower = {tool.name.lower(): tool for tool in tools.tools}
        self._skill_by_name = {skill.name: skill for skill in skills.skills}
        self._agent_by_name = {agent.name: agent for agent in agents.agents}

    def allowed_tools(self, agent_name: str) -> RuleTuple:
        agent = self._agent(agent_name)
        base = self._resolve_rule(agent.capabilities.tools_allow, self._tool_names(), "tool")
        denied = self._resolve_rule(agent.capabilities.tools_deny, self._tool_names(), "tool")
        return tuple(name for name in base if name not in set(denied))

    def is_tool_allowed(self, agent_name: str, tool_name: str) -> bool:
        return self._canonical_tool(tool_name) in self.allowed_tools(agent_name)

    def assert_tool_allowed(self, agent_name: str, tool_name: str) -> None:
        if not self.is_tool_allowed(agent_name, tool_name):
            raise PermissionError(f"Tool '{tool_name}' is not allowed for agent '{agent_name}'")

    def allowed_skills(self, agent_name: str) -> RuleTuple:
        if not self.is_tool_allowed(agent_name, "Skill"):
            return ()
        agent = self._agent(agent_name)
        base = self._resolve_skill_rule(agent.capabilities.skills_allow)
        denied = self._resolve_skill_rule(agent.capabilities.skills_deny)
        return tuple(name for name in base if name not in set(denied))

    def skill_descriptions(self, agent_name: str) -> Tuple[Tuple[str, str], ...]:
        return tuple(
            (name, self._skill_by_name[name].description or "No description")
            for name in self.allowed_skills(agent_name)
            if name in self._skill_by_name
        )

    def assert_skill_allowed(self, agent_name: str, skill_name: str) -> None:
        skills = self.allowed_skills(agent_name)
        if not skills:
            raise PermissionError(f"No skills are allowed for agent '{agent_name}'")
        if skill_name not in skills:
            raise PermissionError(f"Skill '{skill_name}' is not allowed for agent '{agent_name}'")

    def allowed_subagents(self, agent_name: str) -> RuleTuple:
        if not self.is_tool_allowed(agent_name, "Task"):
            return ()
        rule = self._agent(agent_name).capabilities.subagents_allow
        if rule.mode == "denyall":
            return ()
        if rule.mode == "acceptall":
            names = [a.name for a in self._agents.agents if self._is_subagent(a) and a.name != agent_name]
            return tuple(sorted(names, key=str.lower))
        return tuple(rule.names)

    def subagent_descriptions(self, agent_name: str) -> Tuple[Tuple[str, str], ...]:
        return tuple(
            (name, self._agent_by_name[name].description or "")
            for name in self.allowed_subagents(agent_name)
            if name in self._agent_by_name
        )

    def assert_subagent_allowed(self, agent_name: str, subagent_name: str) -> None:
        subagents = self.allowed_subagents(agent_name)
        if not subagents:
            raise PermissionError(f"No subagents are allowed for agent '{agent_name}'")
        if subagent_name not in subagents:
            raise PermissionError(
                f"Subagent '{subagent_name}' is not allowed for agent '{agent_name}'"
            )

    def validate_all_agents(self) -> RuleTuple:
        errors = []
        for agent in sorted(self._agents.agents, key=lambda item: item.name):
            errors.extend(self._validate_agent(agent))
        return tuple(errors)

    def _validate_agent(self, agent: Any) -> list[str]:
        errors = []
        errors.extend(self._unknown_tools(agent, "tools", agent.capabilities.tools_allow))
        errors.extend(self._unknown_tools(agent, "denytools", agent.capabilities.tools_deny))
        if self.is_tool_allowed(agent.name, "Task"):
            errors.extend(self._validate_subagents(agent))
        if self.is_tool_allowed(agent.name, "Skill"):
            errors.extend(self._validate_skills(agent, "allowskills", agent.capabilities.skills_allow))
            errors.extend(self._validate_skills(agent, "denyskills", agent.capabilities.skills_deny))
        return errors

    def _validate_skills(self, agent: Any, field_name: str, rule: NameSetRule) -> list[str]:
        if rule.mode != "list":
            return []
        unknown = [name for name in rule.names if name not in self._skill_by_name]
        disabled = [name for name in rule.names if self._disabled_skill(name)]
        return self._format_errors(agent.name, field_name, "skill", unknown, disabled)

    def _validate_subagents(self, agent: Any) -> list[str]:
        rule = agent.capabilities.subagents_allow
        if rule.mode != "list":
            return []
        errors = []
        names = list(rule.names)
        unknown = [name for name in names if name not in self._agent_by_name]
        wrong = [name for name in names if name in self._agent_by_name and not self._is_subagent(self._agent_by_name[name])]
        if agent.name in names:
            errors.append(f"{agent.name}: allowsubagents contains self reference: {agent.name}")
        errors.extend(self._format_errors(agent.name, "allowsubagents", "agent", unknown, []))
        if wrong:
            errors.append(f"{agent.name}: allowsubagents references non-subagent agent(s): {', '.join(wrong)}")
        return errors

    def _unknown_tools(self, agent: Any, field_name: str, rule: NameSetRule) -> list[str]:
        if rule.mode != "list":
            return []
        unknown = [name for name in rule.names if self._canonical_tool(name) is None]
        if not unknown:
            return []
        return [f"{agent.name}: {field_name} references unknown tool(s): {', '.join(unknown)}"]

    def _resolve_skill_rule(self, rule: NameSetRule) -> RuleTuple:
        names = tuple(skill.name for skill in self._skills.skills if skill.enabled)
        if rule.mode == "acceptall":
            return tuple(sorted(names, key=str.lower))
        if rule.mode == "denyall":
            return ()
        return tuple(rule.names)

    def _resolve_rule(self, rule: NameSetRule, names: RuleTuple, item_type: str) -> RuleTuple:
        if rule.mode == "acceptall":
            return tuple(sorted(names, key=str.lower))
        if rule.mode == "denyall":
            return ()
        if item_type == "tool":
            return tuple(name for raw in rule.names if (name := self._canonical_tool(raw)))
        return tuple(rule.names)

    def _format_errors(
        self, agent_name: str, field_name: str, item_type: str, unknown: list[str], disabled: list[str]
    ) -> list[str]:
        errors = []
        if unknown:
            errors.append(f"{agent_name}: {field_name} references unknown {item_type}(s): {', '.join(unknown)}")
        if disabled:
            errors.append(f"{agent_name}: {field_name} references disabled {item_type}(s): {', '.join(disabled)}")
        return errors

    def _tool_names(self) -> RuleTuple:
        return tuple(tool.name for tool in self._tools.tools)

    def _agent(self, agent_name: str) -> Any:
        return self._agent_by_name[agent_name]

    def _canonical_tool(self, tool_name: str) -> Optional[str]:
        tool = self._tool_by_lower.get(str(tool_name).lower())
        return tool.name if tool else None

    def _disabled_skill(self, name: str) -> bool:
        skill = self._skill_by_name.get(name)
        return bool(skill and not skill.enabled)

    def _is_subagent(self, agent: Any) -> bool:
        mode = getattr(agent.mode, "value", agent.mode)
        return mode in ("subagent", "all")
