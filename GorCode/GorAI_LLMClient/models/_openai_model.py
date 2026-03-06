import json
from openai import OpenAI, APIConnectionError, APITimeoutError
from ._model_base import model_base
from ..message._message_base import MsgReturn

class openai_chat_completetion_model(model_base):
    def __init__(self, base_url, api_key, model_name, stream=True, extra_args=None, router=None):
        super().__init__(base_url, api_key, model_name, stream, extra_args, router)
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key
        )

    def model_chat(self, messages):
        """
        OpenAI聊天完成接口实现

        Args:
            messages: 对话消息列表

        Yields:
            MsgReturn对象
        """
        try:
            # 构建请求参数
            request_params = {
                "model": self.model_name,
                "messages": messages,
                "stream": self.stream,
                **self.extra_args
            }

            # 如果有工具，添加到请求中
            if self.tools:
                request_params["tools"] = self.tools

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

    def _handle_stream_response(self, request_params):
        """处理流式响应"""
        response = self.client.chat.completions.create(**request_params)

        reasoning_content = ""
        content = ""
        tool_calls_dict = {}  # 使用字典按index追踪每个工具，避免并行工具调用时名称拼接错误

        for chunk in response:
            if chunk.choices:
                choice = chunk.choices[0]
                delta = choice.delta

                # 处理思考内容
                if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                    reasoning_delta = delta.reasoning_content
                    reasoning_content += reasoning_delta
                    yield MsgReturn(
                        content=reasoning_delta,
                        type="reasoning",
                        gorType="think",
                        extra={"delta": reasoning_delta},
                        default_response=chunk
                    )

                # 处理回答内容
                if delta.content:
                    content_delta = delta.content
                    content += content_delta
                    yield MsgReturn(
                        content=content_delta,
                        type="content",
                        gorType="answer",
                        extra={"delta": content_delta},
                        default_response=chunk
                    )

                # 处理工具调用
                if delta.tool_calls:
                    for tool_call_delta in delta.tool_calls:
                        tool_index = tool_call_delta.index
                        
                        if tool_index is not None:
                            if tool_index not in tool_calls_dict:
                                # 新工具：创建新的工具调用记录
                                tool_calls_dict[tool_index] = {
                                    "id": tool_call_delta.id or "",
                                    "type": "function",
                                    "function": {
                                        "name": tool_call_delta.function.name or "",
                                        "arguments": tool_call_delta.function.arguments or ""
                                    }
                                }
                            else:
                                # 现有工具：继续拼接当前工具的数据
                                current_tool = tool_calls_dict[tool_index]
                                if tool_call_delta.id and not current_tool['id']:
                                    current_tool['id'] = tool_call_delta.id
                                if tool_call_delta.function and tool_call_delta.function.name:
                                    current_tool['function']['name'] += tool_call_delta.function.name
                                if tool_call_delta.function and tool_call_delta.function.arguments:
                                    current_tool['function']['arguments'] += tool_call_delta.function.arguments

        # 将字典转换为按index排序的列表，只保留有id的工具
        tool_calls = [tool_calls_dict[i] for i in sorted(tool_calls_dict.keys()) if tool_calls_dict[i]['id']]

        # print(tool_calls)
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
                "reasoning_content": reasoning_content,
                "content": content,
                "tool_calls": tool_calls
            },
            default_response=None
        )

    def _handle_normal_response(self, request_params):
        """处理非流式响应"""
        response = self.client.chat.completions.create(**request_params)

        choice = response.choices[0]
        message = choice.message

        # 处理回答内容
        if message.content:
            yield MsgReturn(
                content=message.content,
                type="content",
                gorType="answer",
                extra={"message": message},
                default_response=response
            )

        # 处理工具调用
        if message.tool_calls:
            for tool_call in message.tool_calls:
                tool_call_dict = {
                    "id": tool_call.id,
                    "type": tool_call.type,
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments
                    }
                }
                yield MsgReturn(
                    content=json.dumps(tool_call_dict, ensure_ascii=False),
                    type="tool_calls",
                    gorType="tool",
                    extra={"tool_call": tool_call_dict},
                    default_response=response
                )

        # 返回结束标志
        yield MsgReturn(
            content="",
            type="end",
            gorType="end",
            extra={"message": message},
            default_response=response
        )

