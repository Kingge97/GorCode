import json
from anthropic import Anthropic, APIConnectionError, APITimeoutError
from ._model_base import model_base
from ..message._message_base import MsgReturn

class anthropic_model(model_base):
    def __init__(self, base_url, api_key, model_name, stream=True, extra_args=None, router=None):
        super().__init__(base_url, api_key, model_name, stream, extra_args, router)
        # 初始化Anthropic客户端
        self.client = Anthropic(
            base_url=self.base_url,
            api_key=self.api_key,
            auth_token=self.api_key
        )

    def model_chat(self, messages):
        """
        Anthropic模型聊天实现

        Args:
            messages: 对话消息列表

        Yields:
            MsgReturn对象
        """
        try:
            # 转换消息格式为Anthropic格式
            anthropic_messages = self._convert_messages_to_anthropic(messages)

            # 构建请求参数
            request_params = {
                "model": self.model_name,
                "messages": anthropic_messages,
                "stream": self.stream,
                "max_tokens": 4096,  # 默认值，可以在extra_args中覆盖
                **self.extra_args
            }

            # 如果有工具，添加到请求中
            if self.tools:
                request_params["tools"] = self._convert_openai_tools_to_anthropic(self.tools)

            if self.stream:
                yield from self._handle_stream_response(request_params)
            else:
                yield from self._handle_normal_response(request_params)

        except (APIConnectionError, APITimeoutError, ConnectionError) as e:
            # 连接断开错误，可以被恢复
            yield MsgReturn(
                content=f"Connection error: {str(e)}",
                type="error",
                gorType="connection_error",
                extra={"error": str(e), "retryable": True},
                default_response=None
            )
        except Exception as e:
            # 返回错误信息
            yield MsgReturn(
                content=f"Error: {str(e)}",
                type="error",
                gorType="error",
                extra={"error": str(e)},
                default_response=None
            )

    def _convert_messages_to_anthropic(self, messages):
        """将标准消息格式转换为Anthropic格式"""
        anthropic_messages = []

        for message in messages:
            role = message["role"]
            content = message["content"]

            # 处理工具调用结果
            if role == "tool":
                # Anthropic使用"user"角色返回工具结果
                anthropic_messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.get("tool_call_id", ""),
                            "content": content
                        }
                    ]
                })
            elif role == "assistant" and "tool_calls" in message:
                # 处理assistant的工具调用
                content_blocks = []
                if content:
                    content_blocks.append({"type": "text", "text": content})

                for tool_call in message.get("tool_calls", []):
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tool_call["id"],
                        "name": tool_call["function"]["name"],
                        "input": json.loads(tool_call["function"]["arguments"])
                    })

                anthropic_messages.append({
                    "role": "assistant",
                    "content": content_blocks
                })
            else:
                # 普通文本消息
                anthropic_messages.append({
                    "role": role,
                    "content": content
                })

        return anthropic_messages

    def _convert_openai_tools_to_anthropic(self, openai_tools):
        """
        将OpenAI格式的工具转换为Anthropic格式

        Args:
            openai_tools: OpenAI格式的工具列表

        Returns:
            Anthropic格式的工具列表
        """
        anthropic_tools = []
        for tool in openai_tools:
            if tool["type"] == "function":
                function_info = tool["function"]
                anthropic_tools.append({
                    "name": function_info["name"],
                    "description": function_info["description"],
                    "input_schema": function_info["parameters"]
                })
        return anthropic_tools

    def _handle_stream_response(self, request_params):
        """处理流式响应"""
        response = self.client.messages.create(**request_params)

        content = ""
        thinking_content = ""
        tool_calls = []
        current_tool_call = None
        current_content_type = None  # 当前内容块类型："thinking" 或 "text"

        for chunk in response:
            # print(chunk)
            if chunk.type == "message_start":
                # 消息开始
                pass
            elif chunk.type == "content_block_start":
                # 内容块开始
                if chunk.content_block.type == "tool_use":
                    # 工具调用开始
                    current_tool_call = {
                        "id": chunk.content_block.id,
                        "type": "function",
                        "function": {
                            "name": chunk.content_block.name,
                            "arguments": ""
                        }
                    }
                elif chunk.content_block.type == "thinking":
                    # 思考内容块开始
                    current_content_type = "thinking"
                elif chunk.content_block.type == "text":
                    # 文本内容块开始
                    current_content_type = "text"
            elif chunk.type == "content_block_delta":
                # 内容块增量
                if chunk.delta.type == "text_delta":
                    # 文本内容
                    text_delta = chunk.delta.text

                    # 根据当前内容块类型添加到相应的内容变量
                    if current_content_type == "thinking":
                        thinking_content += text_delta
                        content_type = "thinking"
                        gor_type = "think"
                    else:
                        content += text_delta
                        content_type = "text"
                        gor_type = "answer"

                    # 实时发送每个文本增量，不进行缓冲
                    yield MsgReturn(
                        content=text_delta,
                        type=content_type,
                        gorType=gor_type,
                        extra={"delta": text_delta},
                        default_response=chunk
                    )

                elif chunk.delta.type == "thinking_delta":
                    # 思考内容增量
                    thinking_delta = chunk.delta.thinking
                    thinking_content += thinking_delta

                    # 实时发送每个思考增量
                    yield MsgReturn(
                        content=thinking_delta,
                        type="thinking",
                        gorType="think",
                        extra={"delta": thinking_delta},
                        default_response=chunk
                    )

                elif chunk.delta.type == "input_json_delta":
                    # 工具参数增量
                    if current_tool_call:
                        current_tool_call["function"]["arguments"] += chunk.delta.partial_json
            elif chunk.type == "content_block_stop":
                # 内容块结束
                if current_tool_call:
                    # 完成当前工具调用
                    tool_calls.append(current_tool_call)
                    current_tool_call = None

                current_content_type = None
            elif chunk.type == "message_delta":
                # 消息增量（通常包含usage信息）
                pass
            elif chunk.type == "message_stop":
                # 消息结束
                pass

        # 如果有工具调用，返回工具信息
        if tool_calls:
            for tool_call in tool_calls:
                yield MsgReturn(
                    content=json.dumps(tool_call, ensure_ascii=False),
                    type="tool_calls",
                    gorType="tool",
                    extra={"tool_call": tool_call},
                    default_response=None
                )

        # 返回结束标志
        yield MsgReturn(
            content="",
            type="end",
            gorType="end",
            extra={
                "content": content,
                "thinking_content": thinking_content,
                "tool_calls": tool_calls
            },
            default_response=None
        )

    def _handle_normal_response(self, request_params):
        """处理非流式响应"""
        response = self.client.messages.create(**request_params)

        content = ""
        thinking_content = ""
        tool_calls = []

        # 处理内容块
        for content_block in response.content:
            if content_block.type == "text":
                # 文本内容
                content += content_block.text
            elif content_block.type == "thinking":
                # 思考内容
                thinking_content += content_block.thinking
            elif content_block.type == "tool_use":
                # 工具调用
                tool_call = {
                    "id": content_block.id,
                    "type": "function",
                    "function": {
                        "name": content_block.name,
                        "arguments": json.dumps(content_block.input)
                    }
                }
                tool_calls.append(tool_call)

        # 处理思考内容
        if thinking_content:
            yield MsgReturn(
                content=thinking_content,
                type="thinking",
                gorType="think",
                extra={"message": response},
                default_response=response
            )

        # 处理回答内容
        if content:
            yield MsgReturn(
                content=content,
                type="text",
                gorType="answer",
                extra={"message": response},
                default_response=response
            )

        # 处理工具调用
        if tool_calls:
            for tool_call in tool_calls:
                yield MsgReturn(
                    content=json.dumps(tool_call, ensure_ascii=False),
                    type="tool_calls",
                    gorType="tool",
                    extra={"tool_call": tool_call},
                    default_response=response
                )

        # 返回结束标志
        yield MsgReturn(
            content="",
            type="end",
            gorType="end",
            extra={"message": response},
            default_response=response
        )