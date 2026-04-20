"""
Permission Rules
================

Rule engine and settings for permission decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional
import fnmatch

DEFAULT_DENY_LIMIT = 3
DEFAULT_MAX_DIFF_LINES = 40


class PermissionMode(Enum):
    AUTO = "auto"
    DONT_ASK = "dontAsk"
    BYPASS = "bypassPermissions"
    ACCEPT_EDITS = "acceptEdits"


@dataclass(frozen=True)
class PermissionDecision:
    decision: str
    reason: Optional[str] = None
    rule_id: Optional[str] = None


@dataclass(frozen=True)
class PermissionRule:
    rule_id: str
    effect: str
    tools: List[str]
    paths: List[str]
    commands: List[str]

    def matches(self, tool_name: str, metadata: Dict[str, Any]) -> bool:
        if not _match_any(tool_name, self.tools):
            return False
        path_value = metadata.get("file_path") or metadata.get("path") or ""
        if self.paths and not _match_any(path_value, self.paths):
            return False
        command_value = metadata.get("command") or ""
        if self.commands and not _match_any(command_value, self.commands):
            return False
        return True


@dataclass(frozen=True)
class PermissionSettings:
    mode: PermissionMode
    rules: List[PermissionRule]
    classifier_enabled: bool
    deny_limit: int
    classifier_max_diff_lines: int

    @classmethod
    def from_config(cls, config: Any) -> "PermissionSettings":
        settings = getattr(config, "permission_settings", {}) if config else {}
        mode_value = settings.get("mode", PermissionMode.AUTO.value)
        rules = [_parse_rule(rule) for rule in settings.get("rules", [])]
        classifier = settings.get("classifier", {})
        classifier_enabled = classifier.get("enabled", False)
        deny_limit = settings.get("deny_limit", DEFAULT_DENY_LIMIT)
        max_diff = classifier.get("max_diff_lines", DEFAULT_MAX_DIFF_LINES)
        return cls(
            mode=_parse_mode(mode_value),
            rules=rules,
            classifier_enabled=bool(classifier_enabled),
            deny_limit=int(deny_limit),
            classifier_max_diff_lines=int(max_diff),
        )


class PermissionRuleEngine:
    def __init__(self, settings: PermissionSettings) -> None:
        self._settings = settings

    def evaluate(self, tool_name: str, metadata: Dict[str, Any]) -> Optional[PermissionDecision]:
        for rule in self._settings.rules:
            if rule.matches(tool_name, metadata):
                return PermissionDecision(rule.effect, reason="rule", rule_id=rule.rule_id)
        return None

    def classify(self, tool_name: str, metadata: Dict[str, Any]) -> Optional[PermissionDecision]:
        if not self._settings.classifier_enabled:
            return None
        if tool_name not in ("write", "edit"):
            return None
        diff = metadata.get("diff", "")
        if not diff:
            return None
        diff_lines = len(str(diff).splitlines())
        if 0 < diff_lines <= self._settings.classifier_max_diff_lines:
            return PermissionDecision("allow", reason="classifier")
        return None


def _parse_mode(value: str) -> PermissionMode:
    for mode in PermissionMode:
        if mode.value == value:
            return mode
    return PermissionMode.AUTO


def _parse_rule(raw: Dict[str, Any]) -> PermissionRule:
    rule_id = str(raw.get("id") or raw.get("rule_id") or "rule")
    effect = str(raw.get("effect", "ask")).lower()
    tools = _as_list(raw.get("tools"))
    paths = _as_list(raw.get("paths"))
    commands = _as_list(raw.get("commands"))
    return PermissionRule(
        rule_id=rule_id,
        effect=effect,
        tools=tools or ["*"],
        paths=paths or [],
        commands=commands or [],
    )


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _match_any(value: str, patterns: List[str]) -> bool:
    if not patterns:
        return True
    for pattern in patterns:
        if pattern == "*":
            return True
        if fnmatch.fnmatch(value, pattern):
            return True
    return False
