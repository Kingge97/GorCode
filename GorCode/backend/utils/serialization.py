"""
Serialization helpers for dataclasses and common types.
"""

from __future__ import annotations

from dataclasses import MISSING, fields, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional


EnumMode = str  # "value" or "name"


def parse_datetime(value: Any, default: Optional[datetime] = None) -> Optional[datetime]:
    """Parse an ISO-8601 datetime string or return a default."""
    if value is None:
        return default
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _serialize_value(value: Any, enum_mode: EnumMode) -> Any:
    if isinstance(value, Enum):
        return value.value if enum_mode == "value" else value.name
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            return to_dict()
        return dataclass_to_dict(value, enum_mode=enum_mode)
    if isinstance(value, dict):
        return {k: _serialize_value(v, enum_mode) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize_value(v, enum_mode) for v in value]
    return value


def dataclass_to_dict(
    instance: Any,
    *,
    enum_mode: EnumMode = "value",
    field_serializers: Optional[Mapping[str, Callable[[Any], Any]]] = None,
    exclude_fields: Optional[Iterable[str]] = None,
    extra_fields: Optional[Mapping[str, Callable[[Any], Any]]] = None,
) -> Dict[str, Any]:
    """
    Convert a dataclass instance to a dictionary.

    Supports per-field serializers, field exclusion, and extra computed fields.
    """
    if not is_dataclass(instance):
        raise TypeError("dataclass_to_dict expects a dataclass instance")

    serializers = field_serializers or {}
    excludes = set(exclude_fields or [])
    result: Dict[str, Any] = {}

    for field in fields(instance):
        name = field.name
        if name in excludes:
            continue
        value = getattr(instance, name)
        serializer = serializers.get(name)
        if serializer:
            result[name] = serializer(value)
        else:
            result[name] = _serialize_value(value, enum_mode)

    if extra_fields:
        for name, builder in extra_fields.items():
            result[name] = builder(instance)

    return result


def dataclass_from_dict(
    cls: type,
    data: Optional[Mapping[str, Any]],
    *,
    field_deserializers: Optional[Mapping[str, Callable[[Any], Any]]] = None,
    field_defaults: Optional[Mapping[str, Any]] = None,
    field_aliases: Optional[Mapping[str, Iterable[str]]] = None,
) -> Any:
    """
    Create a dataclass instance from a dictionary.

    Allows per-field deserializers, default values for missing fields, and key aliases.
    """
    if data is None:
        data = {}

    deserializers = field_deserializers or {}
    defaults = field_defaults or {}
    aliases = field_aliases or {}

    kwargs: Dict[str, Any] = {}
    for field in fields(cls):
        name = field.name
        key = name
        if key not in data and name in aliases:
            for alias in aliases[name]:
                if alias in data:
                    key = alias
                    break

        if key in data:
            raw = data[key]
            parser = deserializers.get(name)
            kwargs[name] = parser(raw) if parser else raw
            continue

        if name in defaults:
            default_value = defaults[name]
            kwargs[name] = default_value() if callable(default_value) else default_value
            continue

        if field.default is not MISSING or field.default_factory is not MISSING:
            continue

        kwargs[name] = None

    return cls(**kwargs)
