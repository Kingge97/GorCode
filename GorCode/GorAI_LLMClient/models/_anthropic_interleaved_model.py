import json
from ._anthropic_model import anthropic_model
from ..message._message_base import MsgReturn


class anthropic_interleaved_model(anthropic_model):
    """
    Anthropic 交错式思考模型实现
    
    使用 Anthropic SDK 调用支持交错式思考的模型，
    采用特殊的交互方式：在工具调用时将助手的完整响应（包含所有 thinking/text/tool_use 块）
    回传到消息历史中，而非只传递工具调用信息。
    
    主要差异：
    - 继承自 anthropic_model，复用底层 API 调用逻辑
    - 重写 chatToNextLoop 方法，实现交错式思考特有的多轮工具调用方式
    - 工具结果以 Anthropic 格式（user 角色 + tool_result 块）发送
    """
    
    def chatToNextLoop(self, messages, executor, encode_json=None, interrupt_check=None):
        """
        交错式思考风格的对话循环方法，从用户发起对话到下一次等待用户发送
        
        该方法实现交错式思考特有的交互方式：
        1. 调用 LLM 获取响应（可能包含 thinking、text、tool_use 块）
        2. 收集完整的响应块数组（所有 thinking/text/tool_use 块）
        3. 如果有工具调用，将完整的块数组作为 assistant 消息追加到历史
        4. 执行工具并以 Anthropic 格式（user 角色 + tool_result）返回结果
        5. 继续循环直到 LLM 不再需要调用工具
        
        ⚠️ 重要提示：此方法会直接修改传入的 messages 列表，将助手的完整响应
        （包含所有内容块）和工具结果追加到消息历史中。
        
        Args:
            messages: 对话消息列表（会被直接修改）
            executor: 工具执行器，需要有 execute_tool(tool_name, arguments) 方法
            encode_json: 可选的 JSON 编码函数，默认使用 UTF-8 编码
            interrupt_check: 可选的中断检查函数，返回 True 时中断对话
        
        Yields:
            bytes: SSE 格式的事件数据，格式为 b"data: {json}\n\n"
                事件类型包括:
                - thinking: 思考内容
                - answer: 回答内容
                - tool_calls: 工具调用列表
                - tool_execution: 工具执行开始
                - tool_result: 工具执行结果
                - error: 错误信息
                - interrupted: 对话被中断
                - end: 对话结束
        
        Example:
            >>> from GorAI_LLMCLient.executor import SimpleFunctionExecutor
            >>> def get_weather(location):
            ...     return "24℃, sunny"
            >>> executor = SimpleFunctionExecutor({"get_weather": get_weather})
            >>> messages = [{"role": "user", "content": "How's the weather in San Francisco?"}]
            >>> for event in model.chatToNextLoop(messages, executor):
            ...     print(event)
        """
        # 默认的 JSON 编码函数
        if encode_json is None:
            def encode_json(data):
                try:
                    return json.dumps(data, ensure_ascii=False).encode('utf-8')
                except UnicodeEncodeError:
                    # 如果遇到编码错误，使用转义序列
                    safe_data = json.dumps(data, ensure_ascii=True).encode('utf-8')
                    return safe_data
        
        # 默认的中断检查函数（永不中断）
        if interrupt_check is None:
            def interrupt_check():
                return False
        
        # 初始化变量
        is_first_round = True  # 是否是第一轮对话
        has_tool_calls = True  # 是否有工具调用
        
        try:
            # 对话循环
            while is_first_round or has_tool_calls:
                is_first_round = False
                
                thinking_content = ""
                answer_content = ""
                content_blocks = []  # 用于收集完整的响应块（交错式思考关键）
                tool_use_blocks = []  # 工具调用块
                is_answering = False
                
                # 发送思考过程开始标记
                # print("=" * 20 + "思考过程" + "=" * 20)
                
                # 调用 model_chat
                response = self.model_chat(messages)
                
                # 处理响应，收集所有内容块
                for item in response:
                    # 检查中断标志
                    if interrupt_check():
                        # print(f"\n检测到中断请求，停止对话")
                        yield b"data: " + encode_json({'type': 'interrupted', 'message': '对话已被用户中断'}) + b"\n\n"
                        return
                    
                    # 处理错误信息
                    if item.gorType == "error":
                        error_msg = item.content
                        # print(f"\n模型调用错误: {error_msg}")
                        yield b"data: " + encode_json({'type': 'error', 'message': error_msg}) + b"\n\n"
                        return

                    # 处理连接断开错误
                    elif item.gorType == "connection_error":
                        error_msg = item.content
                        # print(f"\n连接断开: {error_msg}")
                        yield b"data: " + encode_json({
                            'type': 'connection_error',
                            'message': error_msg,
                            'can_resume': True
                        }) + b"\n\n"
                        return
                    
                    # 处理思考内容
                    elif item.gorType == "think":
                        thinking_content += item.content
                        # print(item.content, end="", flush=True)
                        yield b"data: " + encode_json({'type': 'thinking', 'content': item.content}) + b"\n\n"
                        
                        # 收集 thinking 块（用于完整响应）
                        # 由于是流式，需要累积 thinking 内容
                    
                    # 处理回答内容
                    elif item.gorType == "answer":
                        if not is_answering:
                            is_answering = True
                            # print("\n" + "=" * 20 + "回复内容" + "=" * 20)
                        
                        answer_content += item.content
                        # print(item.content, end="", flush=True)
                        yield b"data: " + encode_json({'type': 'answer', 'content': item.content}) + b"\n\n"
                    
                    # 处理工具调用
                    elif item.gorType == "tool":
                        tool_call = json.loads(item.content)
                        tool_use_blocks.append(tool_call)
                        # print(f"\n检测到工具调用: {tool_call['function']['name']}")
                    
                    # 处理结束标志
                    elif item.gorType == "end":
                        # print("\n" + "=" * 30 + "本次结束" + "=" * 30)
                        pass
                
                # 构建完整的 content 块数组（交错式思考核心逻辑）
                if thinking_content:
                    content_blocks.append({
                        "type": "thinking",
                        "thinking": thinking_content
                    })
                
                if answer_content:
                    content_blocks.append({
                        "type": "text",
                        "text": answer_content
                    })
                
                # 添加工具调用块
                for tool_call in tool_use_blocks:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tool_call['id'],
                        "name": tool_call['function']['name'],
                        "input": json.loads(tool_call['function']['arguments'])
                    })
                
                # 如果有工具调用，执行工具并继续循环
                if tool_use_blocks:
                    # 检查中断标志
                    if interrupt_check():
                        # print(f"\n检测到中断请求，停止工具执行")
                        yield b"data: " + encode_json({'type': 'interrupted', 'message': '对话已被用户中断'}) + b"\n\n"
                        return
                    
                    # ⚠️ 交错式思考关键：将助手的完整响应（所有块）追加到消息历史
                    messages.append({
                        "role": "assistant",
                        "content": content_blocks
                    })
                    
                    # 发送工具调用通知
                    tool_calls_for_frontend = []
                    for tool in tool_use_blocks:
                        tool_calls_for_frontend.append({
                            "id": tool["id"],
                            "function": {
                                "name": tool["function"]["name"],
                                "arguments": tool["function"]["arguments"]
                            }
                        })
                    yield b"data: " + encode_json({'type': 'tool_calls', 'tool_calls': tool_calls_for_frontend}) + b"\n\n"
                    
                    # 执行工具调用（使用交错式思考/Anthropic 风格）
                    yield from self._execute_tools_interleaved_style(tool_use_blocks, messages, executor, encode_json, interrupt_check)
                    
                    # 继续循环
                    has_tool_calls = True
                else:
                    # 没有工具调用，循环结束
                    has_tool_calls = False
                    
                    # 如果有自然语言回答，追加 assistant 消息到历史记录
                    if answer_content:
                        messages.append({
                            'role': 'assistant',
                            'content': answer_content
                        })
            
            yield b"data: " + encode_json({'type': 'end'}) + b"\n\n"
        
        except Exception as e:
            error_msg = f"响应错误: {str(e)}"
            # print(f"响应错误: {e}")
            import traceback
            # print(traceback.format_exc())
            yield b"data: " + encode_json({'type': 'error', 'message': error_msg}) + b"\n\n"
    
    def _execute_tools_interleaved_style(self, tool_use_blocks, messages, executor, encode_json, interrupt_check):
        """
        以交错式思考/Anthropic 风格执行工具调用并更新消息历史
        
        交错式思考风格特点：
        - 工具结果以 user 角色发送
        - 内容格式为 tool_result 块数组
        
        Args:
            tool_use_blocks: 工具调用信息列表
            messages: 消息历史列表（会被直接修改）
            executor: 工具执行器
            encode_json: JSON 编码函数
            interrupt_check: 中断检查函数
        
        Yields:
            bytes: SSE 格式的事件数据
        """
        # print("\n开始工具调用")
        # print("工具数量：" + str(len(tool_use_blocks)))
        
        # 执行所有工具调用
        tool_results = []
        
        for tool in tool_use_blocks:
            # 检查中断标志
            if interrupt_check():
                # print(f"\n检测到中断请求，停止工具执行")
                yield b"data: " + encode_json({'type': 'interrupted', 'message': '对话已被用户中断'}) + b"\n\n"
                return
            
            try:
                # 解析工具参数
                tool_args = self._try_parse_tool_arguments(tool["function"]["arguments"])
                
                if tool_args is None:
                    # JSON解析失败，返回错误
                    error_msg = f"工具参数不是有效的JSON: {tool['function']['arguments']}"
                    # print(f"工具参数校验失败: {error_msg}")
                    yield b"data: " + encode_json({
                        'type': 'tool_result',
                        'tool_name': tool['function'].get('name', 'unknown'),
                        'tool_call_id': tool.get('id', ''),
                        'result': error_msg
                    }) + b"\n\n"
                    
                    # 添加错误结果
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool.get('id', ''),
                        "content": error_msg
                    })
                    continue
                
                tool_name = tool["function"]["name"]
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
                
                # 发送工具结果
                yield b"data: " + encode_json({
                    'type': 'tool_result',
                    'tool_name': tool_name,
                    'tool_call_id': tool_call_id,
                    'result': str(result)
                }) + b"\n\n"
                
                # 收集工具结果（Anthropic 格式）
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": str(result)
                })
            
            except Exception as e:
                error_msg = f"工具执行错误: {str(e)}"
                # print(f"工具执行错误: {e}")
                yield b"data: " + encode_json({
                    'type': 'tool_result',
                    'tool_name': tool_name,
                    'tool_call_id': tool_call_id,
                    'result': error_msg
                }) + b"\n\n"
                
                # 添加错误结果
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": error_msg
                })
        
        # ⚠️ 交错式思考关键：以 user 角色 + tool_result 块数组的形式追加工具结果
        messages.append({
            "role": "user",
            "content": tool_results
        })
