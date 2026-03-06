#!/usr/bin/env python3
"""
GorAI_LLMClient - chatToNextLoop 使用示例
=========================================

本示例展示如何使用 chatToNextLoop 方法实现带工具调用的对话循环。

功能特点:
1. 自动处理多轮对话
2. 自动检测并执行工具调用
3. 将工具结果反馈给 LLM
4. 循环直到 LLM 不再需要调用工具

"""

import json
import sys
import os

# 添加父目录到路径，以便导入 GorAI_LLMCLient
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from GorAI_LLMCLient import create_model, SimpleFunctionExecutor


# ========================================
# 示例 1: 使用 SimpleFunctionExecutor
# ========================================

def example_1_simple_executor():
    """示例1：使用简单的函数执行器"""
    print("=" * 60)
    print("示例 1: 使用 SimpleFunctionExecutor")
    print("=" * 60)

    # 定义工具函数
    def add(a: int, b: int) -> int:
        """加法计算"""
        return a + b

    def multiply(a: int, b: int) -> int:
        """乘法计算"""
        return a * b

    def get_weather(city: str) -> str:
        """获取天气（模拟）"""
        return f"{city}的天气：晴天，温度25°C"

    # 创建工具执行器
    executor = SimpleFunctionExecutor({
        "add": add,
        "multiply": multiply,
        "get_weather": get_weather
    })

    # 创建模型实例
    # 注意：需要替换为实际的 API 配置
    model = create_model(
        base_url="https://api.openai.com/v1",  # 替换为实际的 API 地址
        api_key="your-api-key-here",  # 替换为实际的 API Key
        model_name="gpt-4",
        stream=True,
        router="openai-chat"
    )

    # 初始化工具
    tools = [
        {
            "name": "add",
            "description": "计算两个数的和",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "integer", "description": "第一个数"},
                    "b": {"type": "integer", "description": "第二个数"}
                },
                "required": ["a", "b"]
            }
        },
        {
            "name": "multiply",
            "description": "计算两个数的乘积",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "integer", "description": "第一个数"},
                    "b": {"type": "integer", "description": "第二个数"}
                },
                "required": ["a", "b"]
            }
        },
        {
            "name": "get_weather",
            "description": "获取指定城市的天气",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称"}
                },
                "required": ["city"]
            }
        }
    ]

    # 转换工具格式
    tool_dict = []
    for tool in tools:
        tool_dict.append({
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
            "function": None
        })
    model.model_tool_init(tool_dict)

    # 准备消息
    messages = [
        {"role": "user", "content": "请帮我计算 (3 + 5) * 2 的结果"}
    ]

    # 使用 chatToNextLoop 处理对话
    print("\n开始对话...")
    for event in model.chatToNextLoop(messages, executor):
        # 解析事件
        event_str = event.decode('utf-8')
        if event_str.startswith('data: '):
            data = json.loads(event_str[6:])

            # 根据事件类型处理
            if data['type'] == 'thinking':
                print(f"[思考] {data['content']}", end='', flush=True)
            elif data['type'] == 'answer':
                print(f"[回答] {data['content']}", end='', flush=True)
            elif data['type'] == 'tool_calls':
                print(f"\n[工具调用] {json.dumps(data['tool_calls'], ensure_ascii=False)}")
            elif data['type'] == 'tool_result':
                print(f"[工具结果] {data['tool_name']}: {data['result']}")
            elif data['type'] == 'error':
                print(f"\n[错误] {data['message']}")
            elif data['type'] == 'end':
                print("\n\n[对话结束]")

    print("\n" + "=" * 60)


# ========================================
# 示例 2: 自定义 ToolExecutor
# ========================================

from GorAI_LLMCLient.executor import ToolExecutor


class CustomToolExecutor(ToolExecutor):
    """自定义工具执行器"""

    def __init__(self):
        self.execution_log = []  # 执行日志

    def execute_tool(self, tool_name: str, arguments: dict) -> str:
        """执行工具调用"""
        # 记录执行日志
        self.execution_log.append({
            "tool": tool_name,
            "args": arguments
        })

        # 根据工具名称执行不同的逻辑
        if tool_name == "search_database":
            query = arguments.get("query", "")
            return f"数据库搜索结果：找到 {len(query)} 条相关记录"

        elif tool_name == "send_email":
            to = arguments.get("to", "")
            subject = arguments.get("subject", "")
            return f"邮件已发送到 {to}，主题：{subject}"

        else:
            return f"未知工具：{tool_name}"

    def get_execution_log(self):
        """获取执行日志"""
        return self.execution_log


def example_2_custom_executor():
    """示例2：使用自定义执行器"""
    print("\n\n" + "=" * 60)
    print("示例 2: 使用自定义 ToolExecutor")
    print("=" * 60)

    # 创建自定义执行器
    executor = CustomToolExecutor()

    # 创建模型实例（配置同上）
    model = create_model(
        base_url="https://api.openai.com/v1",
        api_key="your-api-key-here",
        model_name="gpt-4",
        stream=True,
        router="openai-chat"
    )

    # 初始化工具
    tools = [
        {
            "name": "search_database",
            "description": "搜索数据库",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "send_email",
            "description": "发送邮件",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "收件人"},
                    "subject": {"type": "string", "description": "邮件主题"}
                },
                "required": ["to", "subject"]
            }
        }
    ]

    tool_dict = []
    for tool in tools:
        tool_dict.append({
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
            "function": None
        })
    model.model_tool_init(tool_dict)

    # 准备消息
    messages = [
        {"role": "user", "content": "搜索数据库中关于'人工智能'的内容，并发送邮件给 admin@example.com"}
    ]

    # 使用 chatToNextLoop 处理对话
    print("\n开始对话...")
    for event in model.chatToNextLoop(messages, executor):
        # 处理事件（同示例1）
        event_str = event.decode('utf-8')
        if event_str.startswith('data: '):
            data = json.loads(event_str[6:])

            if data['type'] == 'thinking':
                print(f"[思考] {data['content']}", end='', flush=True)
            elif data['type'] == 'answer':
                print(f"[回答] {data['content']}", end='', flush=True)
            elif data['type'] == 'tool_calls':
                print(f"\n[工具调用] {json.dumps(data['tool_calls'], ensure_ascii=False)}")
            elif data['type'] == 'tool_result':
                print(f"[工具结果] {data['tool_name']}: {data['result']}")
            elif data['type'] == 'end':
                print("\n\n[对话结束]")

    # 打印执行日志
    print("\n执行日志:")
    for log in executor.get_execution_log():
        print(f"  - {log['tool']}: {log['args']}")

    print("\n" + "=" * 60)


# ========================================
# 示例 3: 支持中断的对话
# ========================================

def example_3_interruptible_chat():
    """示例3：支持中断的对话"""
    print("\n\n" + "=" * 60)
    print("示例 3: 支持中断的对话")
    print("=" * 60)

    # 创建执行器
    executor = SimpleFunctionExecutor({
        "add": lambda a, b: a + b
    })

    # 创建模型
    model = create_model(
        base_url="https://api.openai.com/v1",
        api_key="your-api-key-here",
        model_name="gpt-4",
        stream=True,
        router="openai-chat"
    )

    # 初始化工具
    tool_dict = [{
        "name": "add",
        "description": "加法",
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"}
            }
        },
        "function": None
    }]
    model.model_tool_init(tool_dict)

    # 中断标志
    should_interrupt = False

    def interrupt_check():
        """中断检查函数"""
        return should_interrupt

    messages = [{"role": "user", "content": "计算1+2"}]

    print("\n开始对话（可中断）...")

    # 模拟：处理几个事件后中断
    event_count = 0
    for event in model.chatToNextLoop(messages, executor, interrupt_check=interrupt_check):
        event_count += 1

        # 模拟：处理5个事件后中断
        if event_count > 5:
            print("\n[触发中断]")
            should_interrupt = True

        event_str = event.decode('utf-8')
        if event_str.startswith('data: '):
            data = json.loads(event_str[6:])

            if data['type'] == 'answer':
                print(f"[回答] {data['content']}", end='', flush=True)
            elif data['type'] == 'interrupted':
                print(f"\n[已中断] {data['message']}")
                break
            elif data['type'] == 'end':
                print("\n[对话结束]")

    print("\n" + "=" * 60)


# ========================================
# 主函数
# ========================================

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════╗
║      GorAI_LLMClient chatToNextLoop 使用示例            ║
╚══════════════════════════════════════════════════════════╝

注意：运行此示例前，请先配置正确的 API 地址和密钥！

本示例包含:
1. 使用 SimpleFunctionExecutor 的基础示例
2. 使用自定义 ToolExecutor 的高级示例
3. 支持中断的对话示例

""")

    # 提示用户
    print("⚠️  警告：此示例需要有效的 API 配置才能运行！")
    print("⚠️  请修改代码中的 base_url 和 api_key 后再运行。")
    print("\n如果已配置，按回车继续...")
    input()

    # 运行示例（取消注释以运行）
    # example_1_simple_executor()
    # example_2_custom_executor()
    # example_3_interruptible_chat()

    print("\n✅ 示例代码说明完毕！")
    print("💡 请取消注释相应的示例函数来运行。")
