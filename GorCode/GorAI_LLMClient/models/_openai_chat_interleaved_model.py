import json
from ._openai_model import openai_chat_completetion_model

class openai_chat_interleaved_model(openai_chat_completetion_model):
    """
    OpenAI Chat 交错式思考模型实现
    
    继承自 openai_chat_completetion_model，重写 chatToNextLoop 方法
    以支持带有 reasoning_content 的交错式思考处理方式
    """
    
    def __init__(self, base_url, api_key, model_name, stream=True, extra_args=None, router=None):
        super().__init__(base_url, api_key, model_name, stream, extra_args, router)
    
    def chatToNextLoop(self, messages, executor, encode_json=None, interrupt_check=None):
        """
        交错式思考专用对话循环方法
        
        与标准实现的关键差异：
        1. 在多轮对话中，只将 content 追加到 messages，不追加 reasoning_content
        2. reasoning_content 仅用于展示思考过程，不参与后续对话上下文
        
        Args:
            messages: 对话消息列表（会被直接修改，添加助手回复和工具结果）
            executor: 工具执行器，需要有 execute_tool(tool_name, arguments) 方法
            encode_json: 可选的 JSON 编码函数，默认使用 UTF-8 编码
            interrupt_check: 可选的中断检查函数，返回 True 时中断对话
        
        Yields:
            bytes: SSE 格式的事件数据
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
        tool_info = []  # 工具调用信息
        
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
                    
                    # 处理思考内容 (reasoning_content)
                    elif item.gorType == "think":
                        reasoning_content += item.content
                        # print(item.content, end="", flush=True)
                        yield b"data: " + encode_json({'type': 'thinking', 'content': item.content}) + b"\n\n"
                    
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
                    
                    # 执行工具调用（使用交错式思考专用的方法）
                    yield from self._execute_tools_in_loop_interleaved(
                        tool_info, messages, answer_content, reasoning_content, executor, encode_json, interrupt_check
                    )
                else:
                    # 没有工具调用，追加 assistant 消息到历史记录
                    # ⚠️ 关键：只追加 content，不追加 reasoning_content
                    if answer_content:
                        messages.append({'role': 'assistant', 'content': answer_content})
            
            yield b"data: " + encode_json({'type': 'end'}) + b"\n\n"
        
        except Exception as e:
            error_msg = f"响应错误: {str(e)}"
            # print(f"响应错误: {e}")
            import traceback
            # print(traceback.format_exc())
            yield b"data: " + encode_json({'type': 'error', 'message': error_msg}) + b"\n\n"
    
    def _execute_tools_in_loop_interleaved(self, tool_info, messages, answer_content, reasoning_content, executor, encode_json, interrupt_check):
        """
        交错式思考专用的工具执行方法
        
        与标准实现的关键差异：
        1. assistant 消息中必须包含 reasoning_content 字段（工具调用时必须）
        2. 消息格式符合交错式思考的多轮对话要求
        
        Args:
            tool_info: 工具调用信息列表
            messages: 消息历史列表（会被直接修改）
            answer_content: 助手的回答内容
            reasoning_content: 助手的思考过程内容
            executor: 工具执行器
            encode_json: JSON 编码函数
            interrupt_check: 中断检查函数
        
        Yields:
            bytes: SSE 格式的事件数据
        """
        # print("\n开始工具调用")
        
        # 构建助手消息：必须包含 content、reasoning_content 和 tool_calls
        # ⚠️ 关键：交错式思考 API 要求带有工具调用的 assistant 消息必须包含 reasoning_content
        assistant_message = {
            "role": "assistant",
            "content": answer_content if answer_content else "",
            "reasoning_content": reasoning_content,  # 必须包含，即使为空字符串
            "tool_calls": []
        }
        
        # 发送工具调用开始通知
        tool_calls_for_frontend = []
        for tool in tool_info:
            tool_calls_for_frontend.append({
                "id": tool["id"],
                "function": {
                    "name": tool["name"],
                    "arguments": tool["arguments"]
                }
            })
            
            # 同时添加到 assistant_message
            assistant_message["tool_calls"].append({
                "id": tool["id"],
                "function": {
                    "name": tool["name"],
                    "arguments": tool["arguments"]
                },
                "type": "function"
            })
        
        # 追加 assistant 消息到历史
        messages.append(assistant_message)
        
        # 发送工具调用通知
        yield b"data: " + encode_json({'type': 'tool_calls', 'tool_calls': tool_calls_for_frontend}) + b"\n\n"
        
        # 执行工具调用
        # print("工具数量：" + str(len(tool_info)))
        for tool in tool_info:
            # 检查中断标志
            if interrupt_check():
                # print(f"\n检测到中断请求，停止工具执行")
                yield b"data: " + encode_json({'type': 'interrupted', 'message': '对话已被用户中断'}) + b"\n\n"
                return
            
            try:
                # 尝试解析工具参数
                tool_args = self._try_parse_tool_arguments(tool["arguments"])
                
                if tool_args is None:
                    # JSON解析失败，返回错误
                    error_msg = f"工具参数不是有效的JSON: {tool['arguments']}"
                    # print(f"工具参数校验失败: {error_msg}")
                    yield b"data: " + encode_json({
                        'type': 'tool_result',
                        'tool_name': tool.get('name', 'unknown'),
                        'tool_call_id': tool.get('id', ''),
                        'result': error_msg
                    }) + b"\n\n"
                    # 添加错误结果到消息历史
                    messages.append({"role": "tool", "tool_call_id": tool.get('id', ''), "content": error_msg})
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
                
                # 发送工具结果
                yield b"data: " + encode_json({
                    'type': 'tool_result',
                    'tool_name': tool_name,
                    'tool_call_id': tool_call_id,
                    'result': str(result)
                }) + b"\n\n"
                
                # 更新消息历史
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
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
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": error_msg
                })
