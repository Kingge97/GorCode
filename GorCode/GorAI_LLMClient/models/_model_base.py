from abc import ABC, abstractmethod
import json
from typing import Optional, Callable

class model_base(ABC):
    def __init__(self, base_url, api_key, model_name, stream=True, extra_args=None, router=None):
        """
        模型基础类

        Args:
            base_url: API基础URL
            api_key: API密钥
            model_name: 模型名称
            stream: 是否使用流式输出
            extra_args: 额外参数
            router: 路由类型
        """
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name
        self.stream = stream
        self.extra_args = extra_args or {}
        self.router = router
        self.tools = []
        self.tool_dict = {}

    @abstractmethod
    def model_chat(self, messages):
        """
        模型对话方法

        Args:
            messages: 对话消息列表

        Returns:
            生成器，返回MsgReturn对象
        """
        pass

    def model_tool_init(self, tool_dict):
        """
        初始化工具

        Args:
            tool_dict: 工具字典列表
        """
        self.tool_dict = {tool["name"]: tool for tool in tool_dict}
        self.tools = self._convert_tools_to_format(tool_dict)

    def _convert_tools_to_format(self, tool_dict):
        """
        将工具字典转换为模型所需的格式

        Args:
            tool_dict: 工具字典列表

        Returns:
            格式化后的工具列表
        """
        tools = []
        for tool in tool_dict:
            tool_schema = {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool.get("parameters", {"type": "object", "properties": {}})
                }
            }
            tools.append(tool_schema)
        return tools

    def _execute_tool(self, tool_name, tool_args):
        """
        执行工具函数

        Args:
            tool_name: 工具名称
            tool_args: 工具参数

        Returns:
            工具执行结果
        """
        if tool_name in self.tool_dict:
            tool_info = self.tool_dict[tool_name]
            func = tool_info["function"]
            return func(**tool_args)
        else:
            raise ValueError(f"Tool {tool_name} not found")

    def _try_parse_tool_arguments(self, arguments_str):
        """
        尝试解析工具参数，包含容错处理

        Args:
            arguments_str: JSON 格式的参数字符串

        Returns:
            dict: 解析后的参数字典，解析失败返回 None
        """
        if not arguments_str or not arguments_str.strip():
            return {}  # 空参数返回空字典

        try:
            # 尝试直接解析
            return json.loads(arguments_str)
        except json.JSONDecodeError:
            # 如果JSON解析失败，尝试修复可能的单引号问题
            try:
                fixed_args = arguments_str.replace("'", '"')
                return json.loads(fixed_args)
            except json.JSONDecodeError as e:
                # 如果仍然失败，返回None表示解析失败
                # print(f"工具参数JSON解析失败: {e}")
                # print(f"原始参数: {arguments_str}")
                return None

    def _is_vision_content(self, result):
        """
        判断工具返回结果是否为视觉内容（图片或图文混合）
        
        符合规范的格式：
        - 纯图片: [{"type": "image_url", "image_url": {"url": "图片URL"}}]
        - 图文混合: [{"type": "text", "text": "文字"}, {"type": "image_url", "image_url": {"url": "图片URL"}}]
        
        Args:
            result: 工具执行结果
            
        Returns:
            bool: 如果是符合规范的视觉内容返回True，否则返回False
        """
        # 如果结果不是列表，则不符合规范
        if not isinstance(result, list):
            return False
        
        # 如果列表为空，则不符合规范
        if len(result) == 0:
            return False
        
        # 检查列表中的每个元素是否符合规范
        for item in result:
            # 每个元素必须是字典且包含type字段
            if not isinstance(item, dict) or 'type' not in item:
                return False
            
            item_type = item.get('type')
            
            # 如果是text类型，必须包含text字段
            if item_type == 'text':
                if 'text' not in item:
                    return False
            
            # 如果是image_url类型，必须包含image_url字段和其中的url字段
            elif item_type == 'image_url':
                if 'image_url' not in item or not isinstance(item['image_url'], dict):
                    return False
                if 'url' not in item['image_url']:
                    return False
            
            # 如果type既不是text也不是image_url，则不符合规范
            else:
                return False
        
        # 所有检查都通过，符合规范
        return True

    def chatToNextLoop(self, messages, executor, encode_json=None, interrupt_check=None):
        """
        对话循环方法，从用户发起对话到下一次等待用户发送

        该方法处理完整的对话循环，包括:
        1. 调用 LLM 获取响应
        2. 处理 LLM 的思考内容和回答
        3. 检测并执行工具调用
        4. 将工具结果反馈给 LLM
        5. 继续循环直到 LLM 不再需要调用工具

        ⚠️ 重要提示：此方法会直接修改传入的 messages 列表，将助手回复和工具调用结果
        追加到消息历史中。这样可以保持完整的对话上下文，便于后续继续对话。

        Args:
            messages: 对话消息列表（会被直接修改，添加助手回复和工具结果）
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
            >>> def add(a, b):
            ...     return a + b
            >>> executor = SimpleFunctionExecutor({"add": add})
            >>> messages = [{"role": "user", "content": "1+2等于几?"}]
            >>> for event in model.chatToNextLoop(messages, executor):
            ...     print(event)
            >>> # messages 现在包含了完整的对话历史，包括助手回复和工具调用
            >>> print(len(messages))  # 会大于 1
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
        # 注意：直接使用传入的 messages，不创建副本，这样工具调用和助手回复会保留在消息历史中
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
                        # 错误时退出循环
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
                        # 连接断开时退出循环，但保留 messages 供恢复使用
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
                    yield from self._execute_tools_in_loop(tool_info, messages, executor, encode_json, interrupt_check)
                else:
                    # 没有工具调用，但有自然语言回答时，追加assistant消息到历史记录
                    if answer_content:
                        messages.append({'role': 'assistant', 'content': answer_content})

            # 循环结束后，如果最后一轮有自然语言回答且之前发生过工具调用，也需要追加
            # 检查最后是否是工具调用后的回答（tool_info从有变为空的情况）
            if not tool_info and answer_content:
                # 检查messages最后一条是否已经是这个assistant回答
                if not (messages and messages[-1].get('role') == 'assistant' and messages[-1].get('content') == answer_content):
                    messages.append({'role': 'assistant', 'content': answer_content})

            yield b"data: " + encode_json({'type': 'end'}) + b"\n\n"

        except Exception as e:
            error_msg = f"响应错误: {str(e)}"
            # print(f"响应错误: {e}")
            import traceback
            # print(traceback.format_exc())
            yield b"data: " + encode_json({'type': 'error', 'message': error_msg}) + b"\n\n"

    def _execute_tools_in_loop(self, tool_info, messages, executor, encode_json, interrupt_check):
        """
        执行工具调用并更新消息历史

        Args:
            tool_info: 工具调用信息列表
            messages: 消息历史列表（会被直接修改，添加助手消息和工具结果）
            executor: 工具执行器
            encode_json: JSON 编码函数
            interrupt_check: 中断检查函数

        Yields:
            bytes: SSE 格式的事件数据
        """
        # print("\n开始工具调用")

        # 构建助手消息
        assistant_message = {"role": "assistant", "content": "", "tool_calls": []}
        messages.append(assistant_message)

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
                # 尝试解析工具参数，包含容错处理
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
                yield b"data: " + encode_json({'type': 'tool_execution', 'tool_name': tool_name, 'tool_call_id': tool_call_id, 'args': tool_args}) + b"\n\n"

                # 执行工具
                result = executor.execute_tool(tool_name, tool_args)
                                
                # print(f"工具执行结果: {result}")

                # 判断结果类型并构建消息
                if self._is_vision_content(result):
                    # 符合视觉内容规范，序列化为JSON字符串
                    # 注意：OpenAI API的tool消息content字段只接受字符串
                    # 但我们可以将结构化数据序列化后传递，模型能理解JSON格式的视觉内容
                    tool_result_content = result
                    # print(f"检测到视觉内容，使用dict格式")
                else:
                    # 普通文本结果，使用字符串格式
                    tool_result_content = str(result)

                # 发送工具结果（前端显示）
                yield b"data: " + encode_json({'type': 'tool_result', 'tool_name': tool_name, 'tool_call_id': tool_call_id, 'result': str(result)}) + b"\n\n"

                # 更新消息历史
                assistant_message["tool_calls"].append({
                    "id": tool_call_id,
                    "function": {"arguments": tool["arguments"], "name": tool["name"]},
                    "type": 'function'
                })
                # 根据结果类型构建工具消息
                messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": tool_result_content})

            except Exception as e:
                error_msg = f"工具执行错误: {str(e)}"
                # print(f"工具执行错误: {e}")
                yield b"data: " + encode_json({'type': 'tool_result', 'tool_name': tool_name, 'tool_call_id': tool_call_id, 'result': error_msg}) + b"\n\n"
                messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": error_msg})


