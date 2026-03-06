"""
工具执行器接口定义
===================

该模块定义了工具执行器的抽象接口，用于在 chatToNextLoop 中执行工具调用。

使用方式:
    1. 继承 ToolExecutor 抽象基类
    2. 实现 execute_tool 方法
    3. 将实例传递给 model.chatToNextLoop()

示例:
    >>> from GorAI_LLMCLient.executor import ToolExecutor
    >>>
    >>> class MyExecutor(ToolExecutor):
    ...     def execute_tool(self, tool_name: str, arguments: dict) -> str:
    ...         # 实现工具调用逻辑
    ...         if tool_name == "calculator":
    ...             return str(eval(arguments["expression"]))
    ...         return "Unknown tool"
    >>>
    >>> executor = MyExecutor()
    >>> for event in model.chatToNextLoop(messages, executor):
    ...     print(event)
"""

from abc import ABC, abstractmethod
from typing import Dict, Any


class ToolExecutor(ABC):
    """
    工具执行器抽象基类

    所有工具执行器都需要继承此类并实现 execute_tool 方法。
    """

    @abstractmethod
    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        执行工具调用

        Args:
            tool_name: 工具名称
            arguments: 工具参数字典

        Returns:
            str: 工具执行结果的字符串表示

        Raises:
            Exception: 工具执行失败时可以抛出异常
        """
        pass


class SimpleFunctionExecutor(ToolExecutor):
    """
    简单函数执行器

    通过函数字典映射来执行工具调用。

    示例:
        >>> def add(a, b):
        ...     return a + b
        >>>
        >>> executor = SimpleFunctionExecutor({"add": add})
        >>> result = executor.execute_tool("add", {"a": 1, "b": 2})
        >>> print(result)  # "3"
    """

    def __init__(self, tool_functions: Dict[str, callable]):
        """
        初始化函数执行器

        Args:
            tool_functions: 工具名称到函数的映射字典
        """
        self.tool_functions = tool_functions

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """执行工具调用"""
        if tool_name not in self.tool_functions:
            raise ValueError(f"Tool '{tool_name}' not found in executor")

        func = self.tool_functions[tool_name]
        result = func(**arguments)
        return str(result)
