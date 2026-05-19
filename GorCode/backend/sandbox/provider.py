"""
Sandbox provider loading.
"""

from __future__ import annotations

import importlib
from typing import Any, Mapping

from .builtin_rules import DefaultRulesSandboxProvider
from .config import SandboxSettings
from .http_provider import HttpSandboxProvider
from .process_provider import ProcessSandboxProvider
from .types import SandboxError, SandboxProvider


def load_provider(settings: SandboxSettings) -> SandboxProvider:
    """Load a sandbox provider from settings."""
    provider = dict(settings.provider)
    provider_type = str(provider.get("type", "builtin")).strip().lower()
    params = dict(provider.get("params") or {})
    params.setdefault("unknown_mutation", settings.unknown_mutation)
    if provider_type == "builtin":
        return _load_builtin(provider, params)
    if provider_type == "python":
        return _load_python(provider, params)
    if provider_type == "process":
        return ProcessSandboxProvider(command=str(provider.get("command", "")), params=params)
    if provider_type == "http":
        return HttpSandboxProvider(url=str(provider.get("url", "")), params=params)
    raise SandboxError(f"Unsupported sandbox provider type: {provider_type}")


def _load_builtin(provider: Mapping[str, Any], params: Mapping[str, Any]) -> SandboxProvider:
    name = str(provider.get("name", "default_rules")).strip()
    if name != "default_rules":
        raise SandboxError(f"Unsupported builtin sandbox provider: {name}")
    return DefaultRulesSandboxProvider(**dict(params))


def _load_python(provider: Mapping[str, Any], params: Mapping[str, Any]) -> SandboxProvider:
    module_name = str(provider.get("module", "")).strip()
    factory_name = str(provider.get("factory", "")).strip()
    if not module_name or not factory_name:
        raise SandboxError("python sandbox provider requires module and factory")
    module = importlib.import_module(module_name)
    factory = getattr(module, factory_name, None)
    if factory is None:
        raise SandboxError(f"Sandbox factory not found: {module_name}.{factory_name}")
    instance = factory(**dict(params))
    if not hasattr(instance, "decide"):
        raise SandboxError("python sandbox provider must implement decide(request)")
    return instance
