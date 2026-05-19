"""
Sandbox configuration model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .types import SandboxError


DEFAULT_CONFIG_PATH = ".gorcode/sandbox.json"
DEFAULT_PROVIDER = {"type": "builtin", "name": "default_rules", "params": {}}
UNKNOWN_MUTATION_VALUES = {"deny", "ask", "allow"}


@dataclass(frozen=True)
class SandboxSettings:
    """Resolved sandbox settings for the current session."""

    enabled: bool = True
    provider: Mapping[str, Any] = field(default_factory=lambda: dict(DEFAULT_PROVIDER))
    config_path: Optional[str] = DEFAULT_CONFIG_PATH
    unknown_mutation: str = "allow"

    @classmethod
    def from_config(cls, config: Any, base_path: Optional[Path] = None) -> "SandboxSettings":
        """Build settings from GorCodeConfig-like objects or dictionaries."""
        raw = _extract_settings(config)
        merged = _merge_external_config(raw, base_path)
        provider = _provider_from(merged)
        unknown = str(merged.get("unknown_mutation", "allow")).strip().lower()
        if unknown not in UNKNOWN_MUTATION_VALUES:
            raise SandboxError(f"Invalid sandbox unknown_mutation: {unknown}")
        return cls(
            enabled=bool(merged.get("enabled", True)),
            provider=provider,
            config_path=merged.get("config_path", DEFAULT_CONFIG_PATH),
            unknown_mutation=unknown,
        )

    def with_enabled(self, enabled: bool) -> "SandboxSettings":
        """Return a settings copy with session enablement changed."""
        return SandboxSettings(
            enabled=enabled,
            provider=dict(self.provider),
            config_path=self.config_path,
            unknown_mutation=self.unknown_mutation,
        )


def _extract_settings(config: Any) -> Dict[str, Any]:
    if config is None:
        return {}
    if isinstance(config, dict):
        raw = config.get("sandbox_settings") or config.get("sandboxSettings")
        return dict(raw or {})
    snake = getattr(config, "sandbox_settings", None)
    camel = getattr(config, "sandboxSettings", None)
    return dict(snake or camel or {})


def _merge_external_config(raw: Dict[str, Any], base_path: Optional[Path]) -> Dict[str, Any]:
    path_value = raw.get("config_path", DEFAULT_CONFIG_PATH)
    path = Path(path_value) if path_value else None
    if path and not path.is_absolute() and base_path:
        path = Path(base_path) / path
    if not path or not path.exists():
        return raw
    try:
        with open(path, "r", encoding="utf-8") as file_obj:
            external = json.load(file_obj)
    except (json.JSONDecodeError, OSError) as exc:
        raise SandboxError(f"Failed to load sandbox config {path}: {exc}") from exc
    merged = dict(raw)
    if isinstance(external, dict):
        merged.update({key: value for key, value in external.items() if key != "version"})
    return merged


def _provider_from(raw: Dict[str, Any]) -> Mapping[str, Any]:
    provider = raw.get("provider") or DEFAULT_PROVIDER
    if not isinstance(provider, dict):
        raise SandboxError("sandbox_settings.provider must be an object")
    resolved = dict(provider)
    resolved.setdefault("type", "builtin")
    if resolved["type"] == "builtin":
        resolved.setdefault("name", "default_rules")
    return resolved
