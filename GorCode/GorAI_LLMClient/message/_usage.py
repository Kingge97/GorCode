import json
from typing import Any, Dict

from ._message_base import MsgReturn


INPUT_TOKENS = "input_tokens"
OUTPUT_TOKENS = "output_tokens"
TOTAL_TOKENS = "total_tokens"
OPENAI_PROMPT_TOKENS = "prompt_tokens"
OPENAI_COMPLETION_TOKENS = "completion_tokens"
USAGE_KEYS = (INPUT_TOKENS, OUTPUT_TOKENS, TOTAL_TOKENS)


def normalize_openai_chat_usage(usage: Any) -> Dict[str, int]:
    return _normalize_usage(
        usage,
        input_key=OPENAI_PROMPT_TOKENS,
        output_key=OPENAI_COMPLETION_TOKENS,
        total_key=TOTAL_TOKENS,
        provider="OpenAI Chat",
    )


def normalize_openai_response_usage(usage: Any) -> Dict[str, int]:
    return _normalize_usage(
        usage,
        input_key=INPUT_TOKENS,
        output_key=OUTPUT_TOKENS,
        total_key=TOTAL_TOKENS,
        provider="OpenAI Response",
    )


def normalize_anthropic_usage(usage: Any) -> Dict[str, int]:
    input_tokens = _read_token_field(usage, INPUT_TOKENS, "Anthropic")
    output_tokens = _read_token_field(usage, OUTPUT_TOKENS, "Anthropic")
    return {
        INPUT_TOKENS: input_tokens,
        OUTPUT_TOKENS: output_tokens,
        TOTAL_TOKENS: input_tokens + output_tokens,
    }


def make_usage_message(usage: Dict[str, int], default_response: Any) -> MsgReturn:
    _validate_usage_dict(usage)
    return MsgReturn(
        content=json.dumps(usage, ensure_ascii=False),
        type="usage",
        gorType="usage",
        extra={"usage": dict(usage)},
        default_response=default_response,
    )


def _normalize_usage(
    usage: Any,
    *,
    input_key: str,
    output_key: str,
    total_key: str,
    provider: str,
) -> Dict[str, int]:
    normalized = {
        INPUT_TOKENS: _read_token_field(usage, input_key, provider),
        OUTPUT_TOKENS: _read_token_field(usage, output_key, provider),
        TOTAL_TOKENS: _read_token_field(usage, total_key, provider),
    }
    _validate_usage_dict(normalized)
    return normalized


def _read_token_field(usage: Any, field_name: str, provider: str) -> int:
    value = _read_field(usage, field_name)
    if value is None:
        raise ValueError(f"{provider} usage missing required field: {field_name}")
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{provider} usage field {field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{provider} usage field {field_name} must be non-negative")
    return value


def _read_field(obj: Any, field_name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(field_name)
    return getattr(obj, field_name, None)


def _validate_usage_dict(usage: Dict[str, int]) -> None:
    for key in USAGE_KEYS:
        value = usage.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"usage field {key} must be an integer")
        if value < 0:
            raise ValueError(f"usage field {key} must be non-negative")
