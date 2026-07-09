from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple

from .capabilities import NameSetRule


def parse_allow_rule(
    value: Any,
    *,
    explicit: bool,
    missing_default: str,
    empty_default: str,
) -> NameSetRule:
    if not explicit:
        return _rule_from_mode(missing_default, False)
    if _is_empty(value):
        return _rule_from_mode(empty_default, True)
    return _parse_value_rule(value, True, empty_default)


def parse_deny_rule(value: Any, *, explicit: bool) -> NameSetRule:
    if not explicit or _is_empty(value):
        return NameSetRule.deny_all(explicit)
    return _parse_value_rule(value, True, "denyall")


def legacy_tools_dict(rule: NameSetRule) -> Dict[str, bool]:
    if rule.mode == "acceptall":
        return {"*": True} if rule.explicit else {}
    if rule.mode == "denyall":
        return {}
    return {name: True for name in rule.names}


def legacy_name_list(rule: NameSetRule) -> list[str]:
    if rule.mode == "acceptall":
        return ["acceptall"]
    if rule.mode == "denyall":
        return []
    return list(rule.names)


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _parse_value_rule(value: Any, explicit: bool, empty_default: str) -> NameSetRule:
    if isinstance(value, str):
        return _parse_string_rule(value, explicit)
    if isinstance(value, dict):
        return _parse_dict_rule(value, explicit, empty_default)
    if isinstance(value, (list, tuple, set)):
        return _parse_iterable_rule(value, explicit)
    return _rule_from_mode(empty_default, explicit)


def _parse_string_rule(value: str, explicit: bool) -> NameSetRule:
    stripped = value.strip()
    lowered = stripped.lower()
    if lowered in ("acceptall", "denyall"):
        return _rule_from_mode(lowered, explicit)
    return NameSetRule.list(_split_names(stripped), explicit)


def _parse_iterable_rule(value: Iterable[Any], explicit: bool) -> NameSetRule:
    names = tuple(str(item).strip() for item in value if str(item).strip())
    if len(names) == 1 and names[0].lower() in ("acceptall", "denyall"):
        return _rule_from_mode(names[0].lower(), explicit)
    return NameSetRule.list(names, explicit)


def _parse_dict_rule(value: Dict[Any, Any], explicit: bool, empty_default: str) -> NameSetRule:
    if not value:
        return _rule_from_mode(empty_default, explicit)
    names = tuple(str(name) for name, enabled in value.items() if bool(enabled))
    if len(names) == 1 and names[0] == "*":
        return NameSetRule.accept_all(explicit)
    return NameSetRule.list(names, explicit)


def _split_names(value: str) -> Tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _rule_from_mode(mode: str, explicit: bool) -> NameSetRule:
    if mode == "acceptall":
        return NameSetRule.accept_all(explicit)
    if mode == "denyall":
        return NameSetRule.deny_all(explicit)
    raise ValueError(f"Unknown name-set rule mode: {mode}")
