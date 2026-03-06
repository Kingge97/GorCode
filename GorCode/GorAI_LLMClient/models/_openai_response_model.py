import json
from openai import OpenAI, APIConnectionError, APITimeoutError
from ._model_base import model_base
from ..message._message_base import MsgReturn


class openai_response_model(model_base):
    """
    OpenAI Response API 模型实现
    
    直接继承自 model_base，独立实现 Response API 的所有功能。
    内部自动管理 previous_response_id 实现对话连续性。
    """
    
    def __init__(self, base_url, api_key, model_name, stream=True, extra_args=None, router=None):
        super().__init__(base_url, api_key, model_name, stream, extra_args, router)
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key
        )
        self.previous_response_id = None  # 维护对话连续性
    
    def _make_text_item(self, text, role):
        # Response API 内容类型：用户消息用 input_text，助手消息用 output_text
        if role == "assistant":
            return {"type": "output_text", "text": str(text)}
        else:
            return {"type": "input_text", "text": str(text)}
    
    def _make_image_item(self, image_data, original_item=None):
        # 支持 {"image_url": {"url": ...}} / {"image": ...} / base64 直接字符串
        image_url = image_data
        if isinstance(image_data, dict):
            image_url = (
                image_data.get("url")
                or image_data.get("data")
                or image_data.get("image")
                or image_data.get("base64")
                or image_data
            )
        image_obj = image_url if isinstance(image_url, dict) else {"url": image_url}
        item = {"type": "input_image", "image_url": image_obj}
        if isinstance(original_item, dict) and "detail" in original_item:
            item["detail"] = original_item["detail"]
        return item
    
    def _make_audio_item(self, audio_item):
        # 兼容 input_audio 格式，如 audio_item 已经是 input_audio 则直接返回
        if isinstance(audio_item, dict) and audio_item.get("type") == "input_audio":
            return audio_item
        if isinstance(audio_item, dict):
            new_item = dict(audio_item)
            new_item["type"] = "input_audio"
            return new_item
        return {"type": "input_audio", "audio": audio_item}
    
    def _normalize_content_item(self, item, role):
        if item is None:
            return []
        if isinstance(item, str):
            return [self._make_text_item(item, role)]
        if not isinstance(item, dict):
            return []
        
        item_type = item.get("type")
        if item_type:
            if item_type.startswith("input_") or item_type.startswith("output_") or item_type in ("function_call", "function_call_output"):
                return [item]
            if item_type == "text":
                return [self._make_text_item(item.get("text", ""), role)]
            if item_type == "image_url":
                return [self._make_image_item(item.get("image_url", {}), item)]
            if item_type == "image":
                return [self._make_image_item(item.get("image", None), item)]
            if item_type in ("audio", "input_audio"):
                return [self._make_audio_item(item)]
            # 其他对象类型：直接保留，保证多模态兼容
            return [item]
        
        # 无显式的 type 参数，根据其内容自动推断
        if "text" in item:
            return [self._make_text_item(item.get("text", ""), role)]
        if "image_url" in item or "image" in item:
            image_val = item.get("image_url", None) or item.get("image", None)
            return [self._make_image_item(image_val, item)]
        if "audio" in item or "audio_url" in item:
            return [self._make_audio_item(item)]
        
        return [item]
    
    def _convert_messages_to_response_input(self, messages):
        """
        将 ChatCompletion 格式 messages 转换为 Response API input 格式，兼容图片和其他多模态内容
        
        使用原生 OpenAI Response API 格式：
        - 助手消息中的 tool_calls 转换为 function_call 项放在 content 中
        - tool 角色消息转换为 function_call_output 项
        """
        input_items = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            
            # 已经是 Response API item 直接保留
            if msg.get("type") in ("function_call_output", "function_call") and "role" not in msg:
                input_items.append(msg)
                continue
            if msg.get("type") in ("input_text", "input_image", "input_audio") and "role" not in msg:
                input_items.append(msg)
                continue
            
            role = msg.get("role", "user")
            content_items = []
            function_call_items = []
            
            # 先处理 tool_calls - 转换为 function_call 项（作为独立项，不放在content中）
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                for tc in tool_calls:
                    func = tc.get("function", {}) if isinstance(tc, dict) else {}
                    call_id = tc.get("id") or tc.get("call_id")
                    function_call_items.append({
                        "type": "function_call",
                        "call_id": call_id,
                        "name": func.get("name", ""),
                        "arguments": func.get("arguments", "")
                    })
            
            # 再处理 content
            content = msg.get("content", None)
            if isinstance(content, list):
                for part in content:
                    normalized = self._normalize_content_item(part, role)
                    # 过滤掉 function_call 类型，它们应该作为独立项
                    for item in normalized:
                        if isinstance(item, dict) and item.get("type") == "function_call":
                            function_call_items.append(item)
                        else:
                            content_items.append(item)
            elif content is not None:
                normalized = self._normalize_content_item(content, role)
                for item in normalized:
                    if isinstance(item, dict) and item.get("type") == "function_call":
                        function_call_items.append(item)
                    else:
                        content_items.append(item)
            
            # tool 角色的消息转为 function_call_output
            if role == "tool":
                tool_call_id = msg.get("tool_call_id") or msg.get("id")
                output = content if content is not None else ""
                if not isinstance(output, str):
                    try:
                        output = json.dumps(output, ensure_ascii=False)
                    except Exception:
                        output = str(output)
                input_items.append({
                    "type": "function_call_output",
                    "call_id": tool_call_id,
                    "output": output
                })
                continue
            
            # 先添加助手消息（只包含content_items）
            if content_items:
                message_item = {
                    "role": role,
                    "content": content_items
                }
                input_items.append(message_item)
            elif role == "assistant" and not content_items:
                # 助手消息如果没有内容，添加一个空内容项
                input_items.append({
                    "role": role,
                    "content": []
                })
            
            # 然后添加 function_call 项（作为input数组中的独立项）
            for fc_item in function_call_items:
                input_items.append(fc_item)
        
        return input_items
    
    def _convert_tools_to_format(self, tool_dict):
        """
        将工具字典转换为 OpenAI Response API 所需的格式
        
        Response API 的工具格式与 Chat Completion API 不同：
        - Response API: {"type": "function", "name": "...", "description": "...", "parameters": {...}}
        - Chat Completion API: {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
        
        Args:
            tool_dict: 工具字典列表
        
        Returns:
            格式化后的工具列表（Response API 格式）
        """
        tools = []
        for tool in tool_dict:
            tool_schema = {
                "type": "function",
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool.get("parameters", {"type": "object", "properties": {}})
            }
            tools.append(tool_schema)
        return tools
    
    def model_chat(self, messages):
        """
        OpenAI Response API 实现
        
        Args:
            messages: 对话消息列表（标准格式，内部自动转换）
        
        Yields:
            MsgReturn对象
        """
        try:
            response_input = self._convert_messages_to_response_input(messages)
            # 构建请求参数
            request_params = {
                **self.extra_args,
                "model": self.model_name,
                "input": response_input,  # Response API 使用 input 而非 messages
                "stream": self.stream
            }
            
            # 如果有 previous_response_id，添加到请求实现对话连续性
            if self.previous_response_id:
                request_params["previous_response_id"] = self.previous_response_id
            
            # 如果有工具，添加到请求中
            if self.tools:
                request_params["tools"] = self.tools
            
            # 调试：打印请求参数
            import json
            # print(f"[DEBUG] Request input: {json.dumps(response_input, ensure_ascii=False, indent=2)[:2000]}")
            
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
        """处理流式响应，解析 Response API 事件流"""
        response = self.client.responses.create(**request_params)
        
        reasoning_content = ""
        content = ""
        tool_calls_dict = {}  # 使用字典按index追踪每个工具
        current_tool_index = None
        response_id = None
        saw_text_delta = False
        
        # 用于调试：收集所有事件类型
        debug_event_types = set()
        
        for event in response:
            event_type = event.type
            debug_event_types.add(event_type)
            
            # 调试：打印每个事件的详细信息
            # print(f"[DEBUG] Event type: {event_type}, Event: {event}")
            
            # 跳过 None 类型的事件（某些第三方兼容API可能会返回）
            if event_type is None:
                # 尝试从兼容事件中提取错误信息
                if hasattr(event, 'code') or hasattr(event, 'message'):
                    error_code = getattr(event, 'code', None)
                    error_message = getattr(event, 'message', None) or "Unknown error"
                    if error_code:
                        error_message = f"[{error_code}] {error_message}"
                    yield MsgReturn(
                        content=f"Response API Error: {error_message}",
                        type="error",
                        gorType="error",
                        extra={"error": error_message},
                        default_response=event
                    )
                    return
                continue
            
            # 保存响应ID
            if event_type == "response.created":
                if hasattr(event, 'response') and event.response:
                    response_id = event.response.id
            
            # 处理文本增量 (OpenAI 官方格式)
            elif event_type == "response.output_text.delta":
                if hasattr(event, 'delta') and event.delta:
                    text_delta = event.delta
                    content += text_delta
                    saw_text_delta = True
                    yield MsgReturn(
                        content=text_delta,
                        type="content",
                        gorType="answer",
                        extra={"delta": text_delta},
                        default_response=event
                    )
            
            # 处理文本完整输出 (done/complete 事件)
            elif event_type in ("response.output_text.done", "response.output_text", "response.output_text.completed"):
                if hasattr(event, 'text') and event.text and not saw_text_delta:
                    text_full = event.text
                    content += text_full
                    saw_text_delta = True
                    yield MsgReturn(
                        content=text_full,
                        type="content",
                        gorType="answer",
                        extra={"text": text_full},
                        default_response=event
                    )
            
            # 处理文本增量 (第三方兼容格式 - 可能直接使用 content)
            elif event_type == "content" or event_type == "text":
                if hasattr(event, 'delta') and event.delta:
                    text_delta = event.delta
                    content += text_delta
                    saw_text_delta = True
                    yield MsgReturn(
                        content=text_delta,
                        type="content",
                        gorType="answer",
                        extra={"delta": text_delta},
                        default_response=event
                    )
                elif hasattr(event, 'content') and event.content:
                    text = event.content
                    content += text
                    saw_text_delta = True
                    yield MsgReturn(
                        content=text,
                        type="content",
                        gorType="answer",
                        extra={"content": text},
                        default_response=event
                    )
            
            # 处理推理内容增量 (OpenAI 官方格式)
            elif event_type == "response.reasoning_summary_text.delta":
                if hasattr(event, 'delta') and event.delta:
                    reasoning_delta = event.delta
                    reasoning_content += reasoning_delta
                    yield MsgReturn(
                        content=reasoning_delta,
                        type="reasoning",
                        gorType="think",
                        extra={"delta": reasoning_delta},
                        default_response=event
                    )
            
            # 处理输出项添加（工具调用开始）
            elif event_type == "response.output_item.added" or event_type == "response.output_item.done":
                if hasattr(event, 'item') and event.item:
                    item = event.item
                    item_type = getattr(item, 'type', '')
                    if item_type == "function_call":
                        # 使用 item.id 作为 tool_key（与 function_call_arguments.delta 的 item_id 对应）
                        item_id = getattr(item, 'id', None)
                        call_id = getattr(item, 'call_id', None) or item_id or ''
                        tool_index = getattr(item, 'index', None)
                        if tool_index is None:
                            tool_index = item_id or call_id or 0
                        tool_key = str(item_id) if item_id else str(tool_index)
                        current_tool_index = tool_key
                        # 如果工具已存在，保留已累积的参数（避免output_item.done覆盖参数）
                        existing_args = ""
                        if tool_key in tool_calls_dict:
                            existing_args = tool_calls_dict[tool_key].get("function", {}).get("arguments", "")
                        # 如果item中有arguments且不为空，使用item中的；否则保留已累积的
                        item_args = getattr(item, 'arguments', '') or ''
                        final_args = item_args if item_args else existing_args
                        tool_calls_dict[tool_key] = {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": getattr(item, 'name', ''),
                                "arguments": final_args
                            }
                        }
                    elif item_type == "message" and not saw_text_delta:
                        # 某些实现将完整文本放在 output_item 里
                        if hasattr(item, 'content') and item.content:
                            for content_item in item.content:
                                text_val = getattr(content_item, 'text', None) or getattr(content_item, 'content', None)
                                if text_val:
                                    content += text_val
                                    saw_text_delta = True
                                    yield MsgReturn(
                                        content=text_val,
                                        type="content",
                                        gorType="answer",
                                        extra={"text": text_val},
                                        default_response=event
                                    )
                    elif item_type in ("output_text", "text") and not saw_text_delta:
                        text_val = getattr(item, 'text', None) or getattr(item, 'content', None)
                        if text_val:
                            content += text_val
                            saw_text_delta = True
                            yield MsgReturn(
                                content=text_val,
                                type="content",
                                gorType="answer",
                                extra={"text": text_val},
                                default_response=event
                            )
            
            # 处理工具调用开始 (第三方兼容格式)
            elif event_type == "tool_calls" or event_type == "function_call":
                if hasattr(event, 'tool_calls') and event.tool_calls:
                    for idx, tc in enumerate(event.tool_calls):
                        if isinstance(tc, dict):
                            tc_id = tc.get('id') or tc.get('call_id') or ''
                            tc_func = tc.get('function', {})
                        else:
                            tc_id = getattr(tc, 'id', None) or getattr(tc, 'call_id', None) or ''
                            tc_func = getattr(tc, 'function', {}) if hasattr(tc, 'function') else {}
                        tool_key = str(idx)
                        tool_calls_dict[tool_key] = {
                            "id": tc_id,
                            "type": "function",
                            "function": {
                                "name": tc_func.get('name', '') if isinstance(tc_func, dict) else getattr(tc_func, 'name', ''),
                                "arguments": tc_func.get('arguments', '') if isinstance(tc_func, dict) else getattr(tc_func, 'arguments', '')
                            }
                        }
                elif hasattr(event, 'name'):
                    # 直接是 function_call 事件
                    tool_index = getattr(event, 'index', None)
                    if tool_index is None:
                        tool_index = getattr(event, 'id', None) or getattr(event, 'call_id', None) or 0
                    tool_key = str(tool_index)
                    current_tool_index = tool_key
                    call_id = getattr(event, 'id', None) or getattr(event, 'call_id', None) or ''
                    tool_calls_dict[tool_key] = {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": getattr(event, 'name', ''),
                            "arguments": getattr(event, 'arguments', '')
                        }
                    }
            
            # 处理工具参数增量 (OpenAI 官方格式)
            elif event_type == "response.function_call_arguments.delta":
                if hasattr(event, 'delta') and event.delta:
                    args_delta = event.delta
                    # 优先使用 item_id 来匹配工具
                    if hasattr(event, 'item_id') and event.item_id is not None:
                        tool_key = str(event.item_id)
                    elif hasattr(event, 'index') and event.index is not None:
                        tool_key = str(event.index)
                    elif hasattr(event, 'call_id') and event.call_id is not None:
                        tool_key = str(event.call_id)
                    else:
                        tool_key = current_tool_index
                    if tool_key is not None and tool_key in tool_calls_dict:
                        tool_calls_dict[tool_key]["function"]["arguments"] += args_delta
            
            # 处理工具参数增量 (第三方兼容格式)
            elif event_type == "function_call_arguments":
                if hasattr(event, 'arguments') and current_tool_index is not None:
                    tool_key = current_tool_index
                    if hasattr(event, 'call_id') and event.call_id is not None:
                        tool_key = str(event.call_id)
                    if tool_key in tool_calls_dict:
                        tool_calls_dict[tool_key]["function"]["arguments"] += event.arguments
            
            # 响应完成，保存 response_id
            elif event_type == "response.completed":
                if hasattr(event, 'response') and event.response:
                    response_id = event.response.id
            
            # 处理响应失败事件
            elif event_type == "response.failed":
                error_message = "Unknown error"
                if hasattr(event, 'response') and event.response:
                    response = event.response
                    # 尝试从 error 字段获取错误信息
                    if hasattr(response, 'error') and response.error:
                        if hasattr(response.error, 'message'):
                            error_message = response.error.message
                        elif hasattr(response.error, 'code'):
                            error_message = f"Error code: {response.error.code}"
                        else:
                            error_message = str(response.error)
                yield MsgReturn(
                    content=f"Response API Error: {error_message}",
                    type="error",
                    gorType="error",
                    extra={"error": error_message},
                    default_response=event
                )
                return
            
            # 处理完成事件 (第三方兼容格式)
            elif event_type == "done" or event_type == "completed":
                if hasattr(event, 'response') and event.response:
                    response_id = event.response.id
        
        # 调试输出
        if not content and not tool_calls_dict:
            # print(f"[DEBUG] 收到的事件类型: {debug_event_types}")
            pass
        
        # 更新 previous_response_id 实现对话连续性
        if response_id:
            self.previous_response_id = response_id
        
        # 将字典转换为按index排序的列表，只保留有id的工具
        tool_calls = [tool_calls_dict[i] for i in sorted(tool_calls_dict.keys()) if tool_calls_dict[i].get('id')]
        
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
        response = self.client.responses.create(**request_params)
        
        # 保存 response_id 实现对话连续性
        if hasattr(response, 'id') and response.id:
            self.previous_response_id = response.id
        
        reasoning_content = ""
        content = ""
        tool_calls = []
        
        # 解析输出内容
        if hasattr(response, 'output') and response.output:
            for item in response.output:
                item_type = getattr(item, 'type', '')
                
                if item_type == "message":
                    # 处理消息内容
                    if hasattr(item, 'content') and item.content:
                        for content_item in item.content:
                            content_type = getattr(content_item, 'type', '')
                            if content_type in ("output_text", "text", "input_text"):
                                text = getattr(content_item, 'text', '') or getattr(content_item, 'content', '')
                                content += text
                                yield MsgReturn(
                                    content=text,
                                    type="content",
                                    gorType="answer",
                                    extra={"text": text},
                                    default_response=response
                                )
                elif item_type in ("output_text", "text"):
                    text = getattr(item, 'text', '') or getattr(item, 'content', '')
                    if text:
                        content += text
                        yield MsgReturn(
                            content=text,
                            type="content",
                            gorType="answer",
                            extra={"text": text},
                            default_response=response
                        )
                
                elif item_type == "function_call":
                    # 处理工具调用
                    tool_call = {
                        "id": getattr(item, 'id', '') or getattr(item, 'call_id', ''),
                        "type": "function",
                        "function": {
                            "name": getattr(item, 'name', ''),
                            "arguments": getattr(item, 'arguments', '')
                        }
                    }
                    tool_calls.append(tool_call)
                    yield MsgReturn(
                        content=json.dumps(tool_call, ensure_ascii=False),
                        type="tool_calls",
                        gorType="tool",
                        extra={"tool_call": tool_call},
                        default_response=response
                    )
                
                elif item_type == "reasoning":
                    # 处理推理内容
                    if hasattr(item, 'summary') and item.summary:
                        for summary_item in item.summary:
                            if getattr(summary_item, 'type', '') == "summary_text":
                                text = getattr(summary_item, 'text', '')
                                reasoning_content += text
                                yield MsgReturn(
                                    content=text,
                                    type="reasoning",
                                    gorType="think",
                                    extra={"text": text},
                                    default_response=response
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
    
    def chatToNextLoop(self, messages, executor, encode_json=None, interrupt_check=None):
        """
        对话循环方法，从用户发起对话到下一次等待用户发送
        
        该方法处理完整的对话循环，包括:
        1. 调用 LLM 获取响应
        2. 处理 LLM 的思考内容和回答
        3. 检测并执行工具调用
        4. 将工具结果反馈给 LLM
        5. 继续循环直到 LLM 不再需要调用工具
        
        Args:
            messages: 对话消息列表（会被直接修改，添加助手回复和工具结果）
            executor: 工具执行器，需要有 execute_tool(tool_name, arguments) 方法
            encode_json: 可选的 JSON 编码函数，默认使用 UTF-8 编码
            interrupt_check: 可选的中断检查函数，返回 True 时中断对话
        
        Yields:
            bytes: SSE 格式的事件数据，格式为 b"data: {json}\n\n"
        """
        # 默认的 JSON 编码函数
        if encode_json is None:
            def encode_json(data):
                try:
                    return json.dumps(data, ensure_ascii=False).encode('utf-8')
                except UnicodeEncodeError:
                    safe_data = json.dumps(data, ensure_ascii=True).encode('utf-8')
                    return safe_data
        
        # 默认的中断检查函数（永不中断）
        if interrupt_check is None:
            def interrupt_check():
                return False
        
        # 初始化变量
        is_first_round = True
        tool_info = []
        
        try:
            # 对话循环
            while is_first_round or tool_info:
                is_first_round = False
                
                reasoning_content = ""
                answer_content = ""
                tool_info = []
                is_answering = False
                
                # 发送思考过程开始标记
                # print("=" * 20 + "思考过程" + "=" * 20)
                
                # 调用 model_chat
                response = self.model_chat(messages)
                
                # 处理响应
                for item in response:
                    # 检查中断标志
                    if interrupt_check():
                        # print(f"\n检测到中断请求，停止对话")
                        yield b"data: " + encode_json({'type': 'interrupted', 'message': '对话已被用户中断'}) + b"\n\n"
                        return
                    
                    # 处理错误信息
                    if item.gorType == "error":
                        error_msg = item.content
                        print(f"\n模型调用错误: {error_msg}")
                        yield b"data: " + encode_json({'type': 'error', 'message': error_msg}) + b"\n\n"
                        return

                    # 处理连接断开错误
                    elif item.gorType == "connection_error":
                        error_msg = item.content
                        yield b"data: " + encode_json({
                            'type': 'connection_error',
                            'message': error_msg,
                            'can_resume': True
                        }) + b"\n\n"
                        return
                    
                    # 处理思考内容
                    elif item.gorType == "think":
                        reasoning_content += item.content
                        # print(item.content, end="", flush=True)
                        yield b"data: " + encode_json({'type': 'thinking', 'content': item.content}) + b"\n\n"
                    
                    # 处理回答内容
                    elif item.gorType == "answer":
                        if not is_answering:
                            is_answering = True
                            # print("\n" + "=" * 20 + "回复内容" + "=" * 20)
                            pass
                        
                        answer_content += item.content
                        # print(item.content, end="", flush=True)
                        yield b"data: " + encode_json({'type': 'answer', 'content': item.content}) + b"\n\n"
                    
                    # 处理工具调用
                    elif item.gorType == "tool":
                        tool_call = json.loads(item.content)
                        tool_info.append({
                            'id': tool_call['id'],
                            'name': tool_call['function']['name'],
                            'arguments': tool_call['function']['arguments']
                        })
                        # print(f"\n检测到工具调用: {tool_call['function']['name']}")
                    
                    # 处理结束标志
                    elif item.gorType == "end":
                        # print("\n" + "=" * 30 + "本次结束" + "=" * 30)
                        pass
                
                # 如果有工具调用，执行工具并继续循环
                if tool_info:
                    # 检查中断标志
                    if interrupt_check():
                        # print(f"\n检测到中断请求，停止工具执行")
                        yield b"data: " + encode_json({'type': 'interrupted', 'message': '对话已被用户中断'}) + b"\n\n"
                        return
                    
                    # 执行工具调用
                    yield from self._execute_tools_in_loop(
                        tool_info, messages, answer_content, reasoning_content,
                        executor, encode_json, interrupt_check
                    )
                else:
                    # 没有工具调用，但有自然语言回答时，追加assistant消息到历史记录
                    if answer_content:
                        messages.append({'role': 'assistant', 'content': answer_content})
            
            # 注意：当发生工具调用时，助手消息（包含tool_calls）已经在 _execute_tools_in_loop 中添加
            # 当没有工具调用时，助手消息已在上面添加
            # 所以这里不需要额外处理
            
            yield b"data: " + encode_json({'type': 'end'}) + b"\n\n"
        
        except Exception as e:
            error_msg = f"响应错误: {str(e)}"
            print(f"响应错误: {e}")
            import traceback
            print(traceback.format_exc())
            yield b"data: " + encode_json({'type': 'error', 'message': error_msg}) + b"\n\n"
    
    def _execute_tools_in_loop(self, tool_info, messages, answer_content, reasoning_content,
                               executor, encode_json, interrupt_check):
        """
        执行工具调用并更新消息历史
        
        使用原生 OpenAI Response API 格式：
        - 助手消息只包含 output_text 类型内容
        - function_call 项作为独立项放在 input 数组中
        - 工具结果使用 function_call_output 类型
        
        Args:
            tool_info: 工具调用信息列表
            messages: 消息历史列表（会被直接修改，添加助手消息和工具结果）
            answer_content: 助手的回答内容
            reasoning_content: 助手的思考过程内容
            executor: 工具执行器
            encode_json: JSON 编码函数
            interrupt_check: 中断检查函数
        
        Yields:
            bytes: SSE 格式的事件数据
        """
        # print("\n开始工具调用")
        
        # 构建 tool_calls 数组（用于前端显示）
        tool_calls_for_frontend = []
        
        for tool in tool_info:
            tool_calls_for_frontend.append({
                "id": tool["id"],
                "function": {
                    "name": tool["name"],
                    "arguments": tool["arguments"]
                }
            })
        
        # 构建 Response API 风格的助手消息（只包含文本内容）
        assistant_message = {
            "role": "assistant",
            "content": []
        }
        if answer_content:
            assistant_message["content"].append(self._make_text_item(answer_content, "assistant"))
        
        # 追加助手消息到历史
        messages.append(assistant_message)
        
        # 添加 function_call 项作为独立消息（不是放在content中）
        for tool in tool_info:
            messages.append({
                "type": "function_call",
                "call_id": tool["id"],
                "name": tool["name"],
                "arguments": tool["arguments"]
            })
        
        # 发送工具调用通知
        yield b"data: " + encode_json({'type': 'tool_calls', 'tool_calls': tool_calls_for_frontend}) + b"\n\n"
        
        # 执行工具调用
        # print("工具数量：" + str(len(tool_info)))
        for tool in tool_info:
            # 检查中断标志
            if interrupt_check():
                print(f"\n检测到中断请求，停止工具执行")
                yield b"data: " + encode_json({'type': 'interrupted', 'message': '对话已被用户中断'}) + b"\n\n"
                return
            
            try:
                # 尝试解析工具参数
                tool_args = self._try_parse_tool_arguments(tool["arguments"])
                
                if tool_args is None:
                    # JSON解析失败，返回错误
                    error_msg = f"工具参数不是有效的JSON: {tool['arguments']}"
                    print(f"工具参数校验失败: {error_msg}")
                    yield b"data: " + encode_json({
                        'type': 'tool_result',
                        'tool_name': tool.get('name', 'unknown'),
                        'tool_call_id': tool.get('id', ''),
                        'result': error_msg
                    }) + b"\n\n"
                    # 添加错误结果到消息历史（Response API: function_call_output）
                    messages.append({
                        "type": "function_call_output",
                        "call_id": tool.get('id', ''),
                        "output": error_msg
                    })
                    continue
                
                tool_name = tool["name"]
                tool_call_id = tool["id"]
                
                # print(f"执行工具: {tool_name}, 参数: {tool_args}")
                
                # 发送工具执行通知
                yield b"data: " + encode_json({
                    'type': 'tool_execution',
                    'tool_name': tool_name,
                    'tool_call_id': tool_call_id,
                    'args': tool_args
                }) + b"\n\n"
                
                # 执行工具
                result = executor.execute_tool(tool_name, tool_args)
                
                # print(f"工具执行结果: {result}")
                
                # 判断结果类型并构建消息
                if self._is_vision_content(result):
                    # 符合视觉内容规范，序列化为JSON字符串
                    tool_result_content = json.dumps(result, ensure_ascii=False)
                    # print(f"检测到视觉内容，使用JSON格式")
                else:
                    # 普通文本结果，使用字符串格式
                    tool_result_content = str(result)
                
                # 发送工具结果
                yield b"data: " + encode_json({
                    'type': 'tool_result',
                    'tool_name': tool_name,
                    'tool_call_id': tool_call_id,
                    'result': str(result)
                }) + b"\n\n"
                
                # Response API 的 function_call_output
                messages.append({
                    "type": "function_call_output",
                    "call_id": tool_call_id,
                    "output": tool_result_content
                })
            
            except Exception as e:
                error_msg = f"工具执行错误: {str(e)}"
                print(f"工具执行错误: {e}")
                yield b"data: " + encode_json({
                    'type': 'tool_result',
                    'tool_name': tool_name,
                    'tool_call_id': tool_call_id,
                    'result': error_msg
                }) + b"\n\n"
                messages.append({
                    "type": "function_call_output",
                    "call_id": tool_call_id,
                    "output": error_msg
                })
