"""Load builtin and external Python compression algorithms."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .config import CompressionAlgorithmConfig, CompressionSettings
from .contracts import (
    CompressionConfigError,
    CompressionRequest,
    CompressionResult,
)


@dataclass(frozen=True)
class LoadedCompressionAlgorithm:
    id: str
    options: Mapping[str, Any]
    _compress: Callable[[CompressionRequest], CompressionResult]

    def compress(self, request: CompressionRequest) -> CompressionResult:
        return self._compress(request)


class CompressionAlgorithmLoader:
    """Load the configured compression algorithm."""

    def __init__(
        self,
        *,
        config_manager=None,
        event_bus=None,
        model_manager=None,
        model_connector=None,
        project_path: Path | None = None,
    ):
        self._config_manager = config_manager
        self._event_bus = event_bus
        self._model_manager = model_manager
        self._model_connector = model_connector
        self._project_path = project_path

    def load(self, settings: CompressionSettings) -> LoadedCompressionAlgorithm:
        config = settings.algorithms[settings.algorithm]
        if config.type == "builtin":
            return self._load_builtin(settings.algorithm, config)
        return self._load_python(settings.algorithm, config)

    def _load_builtin(
        self,
        algorithm_id: str,
        config: CompressionAlgorithmConfig,
    ) -> LoadedCompressionAlgorithm:
        if config.name != "gorcode_builtin":
            raise CompressionConfigError(f"unknown builtin compression algorithm: {config.name}")
        from .algorithms.gorcode_builtin import GorCodeBuiltinCompressionAlgorithm

        algorithm = GorCodeBuiltinCompressionAlgorithm(
            options=config.options,
            config_manager=self._config_manager,
            event_bus=self._event_bus,
            model_manager=self._model_manager,
            model_connector=self._model_connector,
        )
        return LoadedCompressionAlgorithm(
            id=algorithm_id,
            options=config.options,
            _compress=algorithm.compress,
        )

    def _load_python(
        self,
        algorithm_id: str,
        config: CompressionAlgorithmConfig,
    ) -> LoadedCompressionAlgorithm:
        module_path = self._resolve_module_path(config.module_path)
        entrypoint = self._load_entrypoint(module_path, config.entrypoint)
        return LoadedCompressionAlgorithm(
            id=algorithm_id,
            options=config.options,
            _compress=entrypoint,
        )

    def _resolve_module_path(self, module_path: str) -> Path:
        path = Path(module_path)
        if not path.is_absolute() and self._project_path:
            path = self._project_path / path
        if not path.exists():
            raise CompressionConfigError(f"compression module_path does not exist: {path}")
        if path.suffix != ".py":
            raise CompressionConfigError(f"compression module_path must be a .py file: {path}")
        return path

    def _load_entrypoint(self, module_path: Path, entrypoint: str):
        spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
        if spec is None or spec.loader is None:
            raise CompressionConfigError(f"cannot load compression module: {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function = getattr(module, entrypoint, None)
        if function is None:
            raise CompressionConfigError(f"compression entrypoint not found: {entrypoint}")
        if not callable(function):
            raise CompressionConfigError(f"compression entrypoint is not callable: {entrypoint}")
        return function
