import copy
import json

from openai import APIConnectionError, APITimeoutError

from ._openai_chat_interleaved_model import openai_chat_interleaved_model
from ..message._message_base import MsgReturn
from ..message._usage import make_usage_message


class openai_chat_interleaved_qwen35pmodel(openai_chat_interleaved_model):
    """
    Qwen 3.5+ 交错式思考模型实现。

    基于 openai_chat_interleaved_model，并在每次请求前对最新一条消息追加
    cache_control 显式缓存标记，同时增强 usage 输出为 OpenAI 形态并保留旧字段兼容。
    """

    def model_chat(self, messages):
        """在发送请求前为最新消息打缓存标记，然后调用 OpenAI Chat Completions。"""
        try:
            cached_messages = self._build_cached_messages(messages)
            request_params = {
                "model": self.model_name,
                "messages": cached_messages,
                "stream": self.stream,
                **self.extra_args,
            }

            if self.tools:
                request_params["tools"] = self.tools

            if self.stream:
                yield from self._handle_stream_response(request_params)
            else:
                yield from self._handle_normal_response(request_params)

        except (APIConnectionError, APITimeoutError, ConnectionError) as e:
            yield MsgReturn(
                content=f"Connection error: {str(e)}",
                type="error",
                gorType="connection_error",
                extra={"error": str(e), "retryable": True},
                default_response=None,
            )
        except Exception as e:
            yield MsgReturn(
                content=f"Error: {str(e)}",
                type="error",
                gorType="error",
                extra={"error": str(e)},
                default_response=None,
            )

    def _build_cached_messages(self, messages):
        """深拷贝消息并仅为最新消息保留一个 cache_control 标记。"""
        cloned_messages = copy.deepcopy(messages)

        for message in cloned_messages:
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        block.pop("cache_control", None)
            elif isinstance(content, dict):
                content.pop("cache_control", None)

        if not cloned_messages:
            return cloned_messages

        latest_message = cloned_messages[-1]
        latest_content = latest_message.get("content")

        if isinstance(latest_content, list):
            if latest_content:
                last_block = latest_content[-1]
                if isinstance(last_block, dict):
                    last_block["cache_control"] = {"type": "ephemeral"}
                else:
                    latest_content[-1] = {
                        "type": "text",
                        "text": str(last_block),
                        "cache_control": {"type": "ephemeral"},
                    }
            else:
                latest_message["content"] = [
                    {"type": "text", "text": "", "cache_control": {"type": "ephemeral"}}
                ]
        elif isinstance(latest_content, dict):
            latest_content["cache_control"] = {"type": "ephemeral"}
        else:
            latest_message["content"] = [
                {
                    "type": "text",
                    "text": "" if latest_content is None else str(latest_content),
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        return cloned_messages

    def _handle_stream_response(self, request_params):
        """处理流式响应并输出兼容 Qwen 显式缓存字段的 usage。"""
        response = self.client.chat.completions.create(
            **self._with_usage_stream_options(request_params)
        )

        reasoning_content = ""
        content = ""
        tool_calls_dict = {}
        usage = None

        for chunk in response:
            if hasattr(chunk, "usage") and chunk.usage:
                usage = self._normalize_qwen_openai_chat_usage(chunk.usage)

            if chunk.choices:
                choice = chunk.choices[0]
                delta = choice.delta

                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    reasoning_delta = delta.reasoning_content
                    reasoning_content += reasoning_delta
                    yield MsgReturn(
                        content=reasoning_delta,
                        type="reasoning",
                        gorType="think",
                        extra={"delta": reasoning_delta},
                        default_response=chunk,
                    )

                if delta.content:
                    content_delta = delta.content
                    content += content_delta
                    yield MsgReturn(
                        content=content_delta,
                        type="content",
                        gorType="answer",
                        extra={"delta": content_delta},
                        default_response=chunk,
                    )

                if delta.tool_calls:
                    for tool_call_delta in delta.tool_calls:
                        tool_index = tool_call_delta.index

                        if tool_index is not None:
                            if tool_index not in tool_calls_dict:
                                tool_calls_dict[tool_index] = {
                                    "id": tool_call_delta.id or "",
                                    "type": "function",
                                    "function": {
                                        "name": tool_call_delta.function.name or "",
                                        "arguments": tool_call_delta.function.arguments or "",
                                    },
                                }
                            else:
                                current_tool = tool_calls_dict[tool_index]
                                if tool_call_delta.id and not current_tool["id"]:
                                    current_tool["id"] = tool_call_delta.id
                                if tool_call_delta.function and tool_call_delta.function.name:
                                    current_tool["function"]["name"] += tool_call_delta.function.name
                                if tool_call_delta.function and tool_call_delta.function.arguments:
                                    current_tool["function"]["arguments"] += tool_call_delta.function.arguments

        tool_calls = [
            tool_calls_dict[i]
            for i in sorted(tool_calls_dict.keys())
            if tool_calls_dict[i]["id"]
        ]

        if tool_calls:
            for tool_call in tool_calls:
                yield MsgReturn(
                    content=json.dumps(tool_call, ensure_ascii=False),
                    type="tool_calls",
                    gorType="tool",
                    extra={"tool_call": tool_call},
                    default_response=None,
                )

        if usage:
            yield make_usage_message(usage, default_response=None)

        yield MsgReturn(
            content="",
            type="end",
            gorType="end",
            extra={
                "reasoning_content": reasoning_content,
                "content": content,
                "tool_calls": tool_calls,
            },
            default_response=None,
        )

    def _handle_normal_response(self, request_params):
        """处理非流式响应并输出兼容 Qwen 显式缓存字段的 usage。"""
        response = self.client.chat.completions.create(**request_params)

        choice = response.choices[0]
        message = choice.message

        if message.content:
            yield MsgReturn(
                content=message.content,
                type="content",
                gorType="answer",
                extra={"message": message},
                default_response=response,
            )

        if message.tool_calls:
            for tool_call in message.tool_calls:
                tool_call_dict = {
                    "id": tool_call.id,
                    "type": tool_call.type,
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    },
                }
                yield MsgReturn(
                    content=json.dumps(tool_call_dict, ensure_ascii=False),
                    type="tool_calls",
                    gorType="tool",
                    extra={"tool_call": tool_call_dict},
                    default_response=response,
                )

        if hasattr(response, "usage") and response.usage:
            usage = self._normalize_qwen_openai_chat_usage(response.usage)
            yield make_usage_message(usage, default_response=response)

        yield MsgReturn(
            content="",
            type="end",
            gorType="end",
            extra={"message": message},
            default_response=response,
        )

    def _normalize_qwen_openai_chat_usage(self, usage):
        """将 Qwen/OpenAI usage 归一化为 OpenAI 形态并保留旧字段兼容。"""
        prompt_tokens = self._read_int_field(usage, "prompt_tokens")
        completion_tokens = self._read_int_field(usage, "completion_tokens")
        total_tokens = self._read_int_field(usage, "total_tokens")

        prompt_tokens_details = self._read_prompt_tokens_details(usage)

        return {
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "prompt_tokens_details": prompt_tokens_details,
        }

    def _read_prompt_tokens_details(self, usage):
        details = self._read_field(usage, "prompt_tokens_details")

        if isinstance(details, dict):
            normalized_details = dict(details)
        elif details is not None:
            normalized_details = {}
            for key in ("cached_tokens", "cache_creation_input_tokens"):
                value = self._read_field(details, key)
                if isinstance(value, int) and not isinstance(value, bool):
                    normalized_details[key] = value
        else:
            normalized_details = {}

        normalized_details["cached_tokens"] = self._safe_int(
            normalized_details.get("cached_tokens", 0)
        )
        normalized_details["cache_creation_input_tokens"] = self._safe_int(
            normalized_details.get("cache_creation_input_tokens", 0)
        )
        return normalized_details

    def _read_int_field(self, obj, field_name):
        value = self._read_field(obj, field_name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"OpenAI Chat usage field {field_name} must be an integer")
        if value < 0:
            raise ValueError(f"OpenAI Chat usage field {field_name} must be non-negative")
        return value

    def _safe_int(self, value):
        if isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return max(0, value)
        return 0

    def _read_field(self, obj, field_name):
        if isinstance(obj, dict):
            return obj.get(field_name)
        return getattr(obj, field_name, None)
