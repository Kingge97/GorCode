"""Compression settings parsing and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .contracts import CompressionConfigError

DEFAULT_ALGORITHM_ID = "gorcode_builtin"
BEFORE_MODEL_REQUEST = "before_model_request"


def default_compression_settings_dict() -> dict[str, Any]:
    return {
        "enabled": True,
        "algorithm": DEFAULT_ALGORITHM_ID,
        "trigger": {
            "event": BEFORE_MODEL_REQUEST,
            "threshold_ratio": 0.85,
        },
        "algorithms": {
            DEFAULT_ALGORITHM_ID: {
                "type": "builtin",
                "name": DEFAULT_ALGORITHM_ID,
                "options": {
                    "soft_enabled": True,
                    "hard_enabled": True,
                    "hard_keep_turns": 1,
                    "protected_tools": ["skill", "Skill"],
                },
            },
        },
    }


@dataclass(frozen=True)
class CompressionTriggerConfig:
    event: str = BEFORE_MODEL_REQUEST
    threshold_ratio: float = 0.85


@dataclass(frozen=True)
class CompressionAlgorithmConfig:
    type: str
    name: str = ""
    module_path: str = ""
    entrypoint: str = "compress"
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompressionSettings:
    enabled: bool
    algorithm: str
    trigger: CompressionTriggerConfig
    algorithms: Mapping[str, CompressionAlgorithmConfig]


def parse_compression_settings(raw: Mapping[str, Any] | None) -> CompressionSettings:
    payload = _merge_defaults(raw)
    trigger = _parse_trigger(payload.get("trigger", {}))
    algorithms = _parse_algorithms(payload.get("algorithms", {}))
    algorithm_id = str(payload.get("algorithm") or "")
    _validate_selected_algorithm(algorithm_id, algorithms)
    return CompressionSettings(
        enabled=bool(payload.get("enabled", True)),
        algorithm=algorithm_id,
        trigger=trigger,
        algorithms=algorithms,
    )


def _merge_defaults(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    defaults = default_compression_settings_dict()
    if raw is None:
        return defaults
    payload = dict(defaults)
    payload.update(dict(raw))
    payload["trigger"] = {**defaults["trigger"], **dict(payload.get("trigger") or {})}
    payload["algorithms"] = _merge_algorithm_defaults(payload.get("algorithms"))
    return payload


def _merge_algorithm_defaults(raw_algorithms: Any) -> dict[str, Any]:
    defaults = default_compression_settings_dict()["algorithms"]
    if raw_algorithms is None:
        return defaults
    merged = dict(defaults)
    merged.update(dict(raw_algorithms))
    return merged


def _parse_trigger(raw: Mapping[str, Any]) -> CompressionTriggerConfig:
    event = str(raw.get("event") or "")
    ratio = float(raw.get("threshold_ratio", 0))
    if event != BEFORE_MODEL_REQUEST:
        raise CompressionConfigError(
            "compression_settings.trigger.event must be before_model_request"
        )
    if ratio <= 0 or ratio > 1:
        raise CompressionConfigError(
            "compression_settings.trigger.threshold_ratio must be in (0, 1]"
        )
    return CompressionTriggerConfig(event=event, threshold_ratio=ratio)


def _parse_algorithms(raw: Mapping[str, Any]) -> dict[str, CompressionAlgorithmConfig]:
    if not isinstance(raw, Mapping) or not raw:
        raise CompressionConfigError("compression_settings.algorithms must be non-empty")
    return {
        str(algorithm_id): _parse_algorithm_config(str(algorithm_id), value)
        for algorithm_id, value in raw.items()
    }


def _parse_algorithm_config(
    algorithm_id: str,
    raw: Mapping[str, Any],
) -> CompressionAlgorithmConfig:
    if not isinstance(raw, Mapping):
        raise CompressionConfigError(f"compression algorithm '{algorithm_id}' must be an object")
    algorithm_type = str(raw.get("type") or "")
    if algorithm_type not in {"builtin", "python"}:
        raise CompressionConfigError(
            f"compression algorithm '{algorithm_id}' type must be builtin or python"
        )
    return CompressionAlgorithmConfig(
        type=algorithm_type,
        name=str(raw.get("name") or ""),
        module_path=str(raw.get("module_path") or ""),
        entrypoint=str(raw.get("entrypoint") or "compress"),
        options=dict(raw.get("options") or {}),
    )


def _validate_selected_algorithm(
    algorithm_id: str,
    algorithms: Mapping[str, CompressionAlgorithmConfig],
) -> None:
    if not algorithm_id:
        raise CompressionConfigError("compression_settings.algorithm is required")
    if algorithm_id not in algorithms:
        raise CompressionConfigError(
            f"compression_settings.algorithm '{algorithm_id}' is not registered"
        )
