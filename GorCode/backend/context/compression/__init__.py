"""Unified conversation compression system."""

from .config import (
    BEFORE_MODEL_REQUEST,
    DEFAULT_ALGORITHM_ID,
    CompressionAlgorithmConfig,
    CompressionSettings,
    CompressionTriggerConfig,
    default_compression_settings_dict,
    parse_compression_settings,
)
from .contracts import (
    CompressionConfigError,
    CompressionError,
    CompressionRequest,
    CompressionResult,
    CompressionRunResult,
)
from .controller import CompressionController
from .loader import CompressionAlgorithmLoader, LoadedCompressionAlgorithm
from .system_prompt import (
    SYSTEM_MESSAGE_PLACEHOLDER,
    hide_system_message,
    restore_system_message,
    validate_system_message_position,
)
from .token_counter import default_count_tokens

__all__ = [
    "BEFORE_MODEL_REQUEST",
    "DEFAULT_ALGORITHM_ID",
    "CompressionAlgorithmConfig",
    "CompressionAlgorithmLoader",
    "CompressionConfigError",
    "CompressionController",
    "CompressionError",
    "CompressionRequest",
    "CompressionResult",
    "CompressionRunResult",
    "CompressionSettings",
    "CompressionTriggerConfig",
    "LoadedCompressionAlgorithm",
    "SYSTEM_MESSAGE_PLACEHOLDER",
    "default_compression_settings_dict",
    "default_count_tokens",
    "hide_system_message",
    "parse_compression_settings",
    "restore_system_message",
    "validate_system_message_position",
]
