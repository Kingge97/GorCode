"""
UI Renderer
===========

Renders UI elements using Rich.
"""

from typing import Any, Dict, Optional
import json
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.live import Live
from rich.spinner import Spinner
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt
import time

from backend.core.events import Event, EventType


class UIRenderer:
    """
    UI Renderer for GorCode using Rich.
    
    Handles:
    - Event rendering
    - Animation effects
    - Code highlighting
    - Progress indicators
    """
    
    # 读取类工具列表 - 这些工具只显示执行状态，不显示结果内容
    READ_ONLY_TOOLS = {
        "read", "ls", "glob", "grep", 
        "search_codebase", "search_file", "list_dir",
        "search_symbol", "fetch_content", "search_web",
        "get_problems", "get_terminal_output",
    }
    
    # 子代理类工具 - 这些工具会发出自己的事件，不需要显示普通工具调用
    SUBAGENT_TOOLS = {
        "task", "Task",
    }
    
    def __init__(self, console: Console = None, config: Any = None):
        """
        Initialize UI renderer.
        
        Args:
            console: Rich console instance
            config: Optional config with permission_diff_max_lines
        """
        self.console = console or Console()
        self._current_spinner = None
        self._thinking_panel = None
        self._is_thinking = False  # Track if we're in thinking mode
        self._is_answering = False  # Track if we're in answering mode
        self._current_agent_key = None  # Current agent key for display grouping
        self._pending_tool_args = None  # Pending tool arguments for display
        self._diff_preview_max_lines = getattr(config, "permission_diff_max_lines", 100)
        self._diff_page_max_lines = getattr(config, "permission_diff_page_lines", 100)
        self._agent_run_labels: Dict[str, str] = {}  # run_id -> display label
        self._agent_label_counts: Dict[str, int] = {}  # display_name -> count
    
    def render_event(self, event: Event) -> None:
        """
        Render an event.
        
        Args:
            event: Event to render
        """
        handler = {
            EventType.MODEL_THINKING: self._render_thinking,
            EventType.MODEL_ANSWER: self._render_answer,
            EventType.MODEL_TOOL_CALL: self._render_tool_call,
            EventType.MODEL_END: self._render_end,
            EventType.MODEL_ERROR: self._render_error,
            EventType.TOOL_EXECUTION_START: self._render_tool_start,
            EventType.TOOL_RESULT: self._render_tool_result,
            EventType.AGENT_SWITCH: self._render_agent_switch,
            EventType.AGENT_SUBAGENT_START: self._render_subagent_start,
            EventType.AGENT_SUBAGENT_END: self._render_subagent_end,
            EventType.UI_MESSAGE: self._render_message,
            EventType.COMMAND_OUTPUT: self._render_command_output,
            EventType.PERMISSION_REQUEST: self._render_permission_request,
            EventType.USER_REJECTION: self._render_user_rejection,
        }.get(event.event_type)
        
        if handler:
            handler(event)
    
    def _render_thinking(self, event: Event) -> None:
        """Render thinking event."""
        content = event.data.get("content", "") if event.data else ""
        
        # Only print header once when starting thinking
        if not self._is_thinking:
            self.console.print()
            self.console.print("[dim]─" * 40 + " Thinking " + "─" * 40 + "[/dim]")
            self._is_thinking = True
        
        # Print thinking content inline
        if content:
            self.console.print(content, end="", style="dim italic")
    
    def _render_answer(self, event: Event) -> None:
        """Render answer event."""
        content = event.data.get("content", "") if event.data else ""
        agent_label, agent_key, indent = self._resolve_agent_display(event.data or {})
        
        # Close thinking section if we were in thinking mode
        if self._is_thinking:
            self.console.print()  # End thinking line
            self._is_thinking = False
        
        # 检查是否切换了代理，需要重置状态
        if agent_key != self._current_agent_key:
            if self._is_answering:
                self.console.print()  # 结束上一个代理的输出
            self._is_answering = False
            self._current_agent_key = agent_key
        
        # Print header once when starting answer
        if not self._is_answering:
            self.console.print()
            # 显示代理名前缀
            if agent_label:
                if indent:
                    self.console.print(f"{indent}[bold cyan][{agent_label}][/bold cyan]")
                else:
                    self.console.print(f"[bold cyan][{agent_label}][/bold cyan]")
            self._is_answering = True
        
        # Print answer content
        if content:
            self.console.print(content, end="")
    
    def _render_content_with_code(self, content: str) -> None:
        """Render content that may contain code blocks."""
        lines = content.split("\n")
        in_code_block = False
        code_lines = []
        language = ""
        
        for line in lines:
            if line.strip().startswith("```"):
                if in_code_block:
                    # End code block
                    code = "\n".join(code_lines)
                    if code.strip():
                        try:
                            syntax = Syntax(code, language or "text", theme="monokai")
                            self.console.print(syntax)
                        except Exception:
                            self.console.print(code)
                    code_lines = []
                    in_code_block = False
                else:
                    # Start code block
                    language = line.strip()[3:].strip()
                    in_code_block = True
            elif in_code_block:
                code_lines.append(line)
            else:
                self.console.print(line)
        
        # Handle unclosed code block
        if code_lines:
            self.console.print("\n".join(code_lines))
    
    def _render_tool_call(self, event: Event) -> None:
        """Render tool call event."""
        if not event.data:
            return
        
        tool_name = event.data.get("name", "unknown")
        args = event.data.get("arguments", {})
        agent_name = event.data.get("agent_name", None)
        
        # 解析 arguments（可能是 JSON 字符串）
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        
        # Task 工具特殊处理：显示为"启动子代理"
        if tool_name.lower() in self.SUBAGENT_TOOLS:
            # 子代理启动由 AGENT_SUBAGENT_START 事件统一处理
            return
        
        # 普通工具调用不在 toolcall 阶段显示，等 executing 阶段统一显示
        # 保存参数供 executing 阶段使用
        self._pending_tool_args = args
    
    def _render_end(self, event: Event) -> None:
        """Render end event."""
        # Reset state flags
        if self._is_thinking:
            self.console.print()  # End thinking line
            self._is_thinking = False
        if self._is_answering:
            self._is_answering = False
        self._current_agent_key = None
        
        self.console.print()
        self.console.print("[dim]─" * 40 + " End " + "─" * 40 + "[/dim]")
        self.console.print()
    
    def _render_error(self, event: Event) -> None:
        """Render error event."""
        # Reset state flags
        self._is_thinking = False
        self._is_answering = False
        self._current_agent_key = None
        self._current_agent_key = None
        
        error = event.data.get("error", "Unknown error") if event.data else "Unknown error"
        self.console.print()
        self.console.print(f"[red bold]Error:[/red bold] [red]{error}[/red]")
    
    def _render_tool_start(self, event: Event) -> None:
        """Render tool execution start event."""
        if not event.data:
            return
        
        tool_name = event.data.get("tool_name", "unknown")
        agent_name = event.data.get("agent_name", None)
        
        # Task 工具由子代理事件处理，不在这里显示
        if tool_name.lower() in self.SUBAGENT_TOOLS:
            return
        
        self.console.print()
        # 显示代理名前缀（如果有）
        if agent_name:
            self.console.print(f"[bold cyan][{agent_name}][/bold cyan] ", end="")
        
        # 获取工具参数：优先使用事件中的 args，否则使用保存的参数
        args = event.data.get("args", None)
        if args is None:
            args = getattr(self, '_pending_tool_args', None)
        
        # 显示工具名称和参数
        if args and isinstance(args, dict) and args:
            # 格式化参数显示，截断长值
            formatted_args = self._format_args(args)
            self.console.print(f"[yellow]Executing:[/yellow] [cyan]{tool_name}[/cyan] [dim]({formatted_args})[/dim]")
        else:
            self.console.print(f"[yellow]Executing:[/yellow] [cyan]{tool_name}[/cyan]")
        
        # 清除保存的参数
        self._pending_tool_args = None
    
    def _format_args(self, args: dict, max_length: int = 100) -> str:
        """格式化参数显示，截断长值"""
        items = []
        for key, value in args.items():
            value_str = str(value)
            if len(value_str) > max_length:
                value_str = value_str[:max_length] + "..."
            # 处理包含换行或引号的值
            value_str = value_str.replace("\n", " ").replace('"', "'")
            items.append(f"{key}={value_str}")
        
        result = ", ".join(items)
        if len(result) > 300:
            result = result[:300] + "..."
        return result
    
    def _render_tool_result(self, event: Event) -> None:
        """Render tool result event."""
        if not event.data:
            return
        
        tool_name = event.data.get("tool_name", "unknown")
        result = event.data.get("result", "")
        success = event.data.get("success", True)
        agent_name = event.data.get("agent_name", None)
        
        # Task 工具由子代理事件处理，不在这里显示
        if tool_name.lower() in self.SUBAGENT_TOOLS:
            return
        
        # 读取类工具：只显示执行状态，不显示结果内容
        if tool_name.lower() in self.READ_ONLY_TOOLS:
            self.console.print()
            if agent_name:
                self.console.print(f"[bold cyan][{agent_name}][/bold cyan] ", end="")
            if success:
                self.console.print(f"[green]✓[/green] [dim]{tool_name}[/dim] 执行成功")
            else:
                error_msg = result[:200] if result else "未知错误"
                self.console.print(f"[red]✗[/red] [dim]{tool_name}[/dim] 执行失败: {error_msg}")
            return
        
        # Normalize non-string results (e.g., MCP image content list)
        if not isinstance(result, str):
            result = self._stringify_tool_result(result)
        
        # Truncate long results
        if len(result) > 500:
            result = result[:500] + "..."
        
        # Use Text to escape markup characters like [x], [>], [ ]
        result_text = Text(result)
        
        self.console.print()
        if agent_name:
            self.console.print(f"[bold cyan][{agent_name}][/bold cyan] ", end="")
        self.console.print("[green]Result:[/green] ", end="")
        self.console.print(result_text)

    def _stringify_tool_result(self, result: Any) -> str:
        """Convert non-string tool results into a safe, printable string."""
        try:
            sanitized = self._sanitize_tool_result(result)
            if isinstance(sanitized, (dict, list)):
                return json.dumps(sanitized, ensure_ascii=False)
            return str(sanitized)
        except Exception:
            return str(result)

    def _sanitize_tool_result(self, data: Any) -> Any:
        """Sanitize tool results to avoid dumping huge data URLs."""
        if isinstance(data, list):
            return [self._sanitize_tool_result(item) for item in data]
        if isinstance(data, dict):
            # MCP image response: {"type":"image_url","image_url":{"url":"data:..."}}
            if data.get("type") == "image_url" and isinstance(data.get("image_url"), dict):
                url = data.get("image_url", {}).get("url", "")
                if isinstance(url, str) and url.startswith("data:"):
                    return {
                        "type": "image_url",
                        "image_url": {
                            "url": f"<data_url {len(url)} chars>"
                        },
                    }
            sanitized: Dict[str, Any] = {}
            for key, value in data.items():
                if key == "url" and isinstance(value, str) and value.startswith("data:"):
                    sanitized[key] = f"<data_url {len(value)} chars>"
                else:
                    sanitized[key] = self._sanitize_tool_result(value)
            return sanitized
        return data
    
    def _render_agent_switch(self, event: Event) -> None:
        """Render agent switch event."""
        if not event.data:
            return
        
        agent = event.data.get("agent", "unknown")
        self.console.print()
        self.console.print(f"[cyan]Switched to agent:[/cyan] [bold]{agent}[/bold]")
    
    def _render_subagent_start(self, event: Event) -> None:
        """Render subagent start event."""
        if not event.data:
            return
        
        agent_name = event.data.get("agent_name", "unknown")
        description = event.data.get("description", "")
        parent_agent = event.data.get("parent_agent", "")
        agent_run_id = event.data.get("agent_run_id")
        agent_display_name = event.data.get("agent_display_name")
        
        # 构建显示名称：如果有父代理，则显示为 "父代理---子代理"
        if agent_display_name:
            display_name = agent_display_name
        elif parent_agent:
            display_name = f"{parent_agent}---{agent_name}"
        else:
            display_name = agent_name
        
        agent_label = self._get_agent_label(agent_run_id, display_name)
        indent = self._get_indent(display_name)
        
        self.console.print()
        if indent:
            self.console.print(f"{indent}[bold magenta]▶ 启动子代理:[/bold magenta] [bold]{agent_label}[/bold]")
        else:
            self.console.print(f"[bold magenta]▶ 启动子代理:[/bold magenta] [bold]{agent_label}[/bold]")
        if description:
            if indent:
                self.console.print(f"{indent}[dim]任务: {description}[/dim]")
            else:
                self.console.print(f"[dim]任务: {description}[/dim]")
        
        # 更新当前代理名
        self._current_agent_key = agent_run_id or display_name
    
    def _render_subagent_end(self, event: Event) -> None:
        """Render subagent end event."""
        if not event.data:
            return
        
        agent_name = event.data.get("agent_name", "unknown")
        success = event.data.get("success", True)
        output = event.data.get("output", "")
        parent_agent = event.data.get("parent_agent", "")
        agent_run_id = event.data.get("agent_run_id")
        agent_display_name = event.data.get("agent_display_name")
        
        # 构建显示名称
        if agent_display_name:
            display_name = agent_display_name
        elif parent_agent:
            display_name = f"{parent_agent}---{agent_name}"
        else:
            display_name = agent_name
        
        agent_label = self._get_agent_label(agent_run_id, display_name)
        indent = self._get_indent(display_name)
        
        self.console.print()
        if success:
            if indent:
                self.console.print(f"{indent}[bold green]✓ 子代理完成:[/bold green] [bold]{agent_label}[/bold]")
            else:
                self.console.print(f"[bold green]✓ 子代理完成:[/bold green] [bold]{agent_label}[/bold]")
        else:
            if indent:
                self.console.print(f"{indent}[bold red]✗ 子代理失败:[/bold red] [bold]{agent_label}[/bold]")
            else:
                self.console.print(f"[bold red]✗ 子代理失败:[/bold red] [bold]{agent_label}[/bold]")
        
        # 显示子代理输出摘要（如果有）
        if output:
            # 截断输出
            if len(output) > 500:
                output = output[:500] + "..."
            self.console.print()
            # 显示代理名前缀
            if indent:
                self.console.print(f"{indent}[bold cyan][{agent_label}][/bold cyan]")
            else:
                self.console.print(f"[bold cyan][{agent_label}][/bold cyan]")
            self.console.print(output)
    
    def _get_indent(self, display_name: str) -> str:
        """Get indentation for nested subagent display."""
        if not display_name:
            return ""
        depth = display_name.count("---")
        if depth <= 0:
            return ""
        return "  " * depth
    
    def _get_agent_label(self, run_id: Optional[str], display_name: str) -> str:
        """Resolve a stable display label for a subagent run."""
        if not display_name:
            return "unknown"
        if not run_id:
            return display_name
        existing = self._agent_run_labels.get(run_id)
        if existing:
            return existing
        count = self._agent_label_counts.get(display_name, 0) + 1
        self._agent_label_counts[display_name] = count
        label = f"{display_name}#{count}" if count > 1 else display_name
        self._agent_run_labels[run_id] = label
        return label
    
    def _resolve_agent_display(self, data: Dict[str, Any]) -> tuple:
        """Resolve agent label, key, and indent for display."""
        agent_name = data.get("agent_name")
        display_name = data.get("agent_display_name") or agent_name
        run_id = data.get("agent_run_id")
        label = self._get_agent_label(run_id, display_name) if display_name else None
        indent = self._get_indent(display_name or "")
        agent_key = run_id or display_name
        return label, agent_key, indent
    
    def _render_message(self, event: Event) -> None:
        """Render UI message event."""
        if not event.data:
            return
        
        message = event.data.get("message", "")
        self.console.print(f"[dim]{message}[/dim]")
    
    def _render_command_output(self, event: Event) -> None:
        """Render command output event."""
        if not event.data:
            return
        
        output = event.data.get("output", "")
        self.console.print(output)
    
    def _render_permission_request(self, event: Event) -> None:
        """
        Render permission request event.
        
        Note: Actual permission dialog is shown via callback, 
        this is just a placeholder for event logging.
        """
        # Permission dialog is handled by callback, not by event rendering
        # This method exists for completeness but does nothing
        pass
    
    def _render_user_rejection(self, event: Event) -> None:
        """
        Render user rejection event (when user rejects operation without reason).
        
        Args:
            event: Event containing rejection message
        """
        # Reset state flags
        self._is_thinking = False
        self._is_answering = False
        
        message = event.data.get("message", "操作被用户拒绝") if event.data else "操作被用户拒绝"
        
        self.console.print()
        self.console.print(Panel(
            Text(message, style="yellow"),
            title="[bold yellow]⚠ 操作已取消[/bold yellow]",
            border_style="yellow",
        ))
    
    def render_welcome(self) -> None:
        """Render welcome screen."""
        title = Text()
        title.append("GorCode", style="bold cyan")
        title.append(" v0.1.0", style="dim")
        
        self.console.print()
        self.console.print(Panel.fit(
            title,
            subtitle="[italic dim]AI-Powered CLI Coding Assistant[/italic dim]",
            border_style="cyan",
        ))
        self.console.print()
    
    def render_help(self) -> None:
        """Render help information."""
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Command", style="cyan")
        table.add_column("Description")
        
        commands = [
            ("/help", "Show this help message"),
            ("/agent <name>", "Switch to a different agent (build, plan)"),
            ("/model <name>", "Switch to a different model"),
            ("/init", "Initialize GorCode in the current directory"),
            ("/mcps", "Manage MCP servers"),
            ("/skills", "Manage skills"),
            ("/new", "Start a new session"),
            ("/history list", "List session history"),
            ("/history load <id>", "Load a session from history"),
            ("/history search <query>", "Search session history"),
            ("/debug on|off|status", "Control debug mode"),
            ("/compact [--force]", "Compact conversation context"),
            ("/context status|stats", "View context and cache statistics"),
            ("/permission [status|grant|revoke|clear]", "Manage session permissions"),
            ("/exit", "Exit GorCode"),
        ]
        
        for cmd, desc in commands:
            table.add_row(cmd, desc)
        
        self.console.print()
        self.console.print(Panel(table, title="[bold]Available Commands[/bold]", border_style="cyan"))
        self.console.print()
    
    def render_agent_list(self, agents: list) -> None:
        """Render list of agents."""
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Name", style="cyan")
        table.add_column("Mode")
        table.add_column("Description")
        
        for agent in agents:
            mode = f"[yellow]{agent.mode.value}[/yellow]"
            table.add_row(agent.name, mode, agent.description or "")
        
        self.console.print()
        self.console.print(Panel(table, title="[bold]Available Agents[/bold]", border_style="cyan"))
        self.console.print()
    
    def render_model_list(self, models: Dict[str, Any]) -> None:
        """Render list of models."""
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Name", style="cyan")
        table.add_column("Router")
        table.add_column("Model")
        
        for name, model in models.items():
            router = getattr(model, 'router', 'unknown')
            model_name = getattr(model, 'model_name', str(model))
            table.add_row(name, router, model_name)
        
        self.console.print()
        self.console.print(Panel(table, title="[bold]Available Models[/bold]", border_style="cyan"))
        self.console.print()
    
    def show_spinner(self, message: str = "Processing...") -> None:
        """Show a spinner with a message."""
        self._current_spinner = Spinner("dots", text=message)
        self.console.print(self._current_spinner)
    
    def hide_spinner(self) -> None:
        """Hide the current spinner."""
        self._current_spinner = None
    
    def print(self, message: str = "", style: str = None) -> None:
        """Print a message with optional style."""
        if style:
            self.console.print(f"[{style}]{message}[/{style}]")
        else:
            self.console.print(message)
    
    def print_error(self, message: str) -> None:
        """Print an error message."""
        self.console.print(f"[red bold]Error:[/red bold] [red]{message}[/red]")
    
    def print_success(self, message: str) -> None:
        """Print a success message."""
        self.console.print(f"[green bold]Success:[/green bold] [green]{message}[/green]")
    
    def print_warning(self, message: str) -> None:
        """Print a warning message."""
        self.console.print(f"[yellow bold]Warning:[/yellow bold] [yellow]{message}[/yellow]")
    
    def clear(self) -> None:
        """Clear the console."""
        self.console.clear()
    
    def show_permission_dialog(
        self,
        permission_type: str,
        metadata: Dict[str, Any]
    ) -> tuple:
        """
        Show permission dialog and get user response.
        
        Args:
            permission_type: Type of permission (write, edit, bash, bash_delete)
            metadata: Permission metadata (file_path, command, diff, etc.)
            
        Returns:
            Tuple of (response, reason):
            - response: 'once', 'always', or 'reject'
            - reason: Rejection reason string (None if not rejected)
        """
        self.console.print()
        self.console.print("=" * 80)
        self.console.print("[bold yellow]⚠️  权限确认请求[/bold yellow]", justify="center")
        self.console.print("=" * 80)
        self.console.print()
        
        # Show different content based on permission type
        if permission_type in ("write", "edit"):
            file_path = metadata.get("file_path", "unknown")
            diff = metadata.get("diff", "")
            
            self.console.print(f"[bold cyan]操作类型:[/bold cyan] {permission_type.upper()}")
            self.console.print(f"[bold cyan]目标文件:[/bold cyan] {file_path}")
            self.console.print()
            
            # Show diff if available
            if diff:
                self.console.print("[bold yellow]代码变更内容:[/bold yellow]")
                
                # Truncate diff if too long
                max_lines = max(1, self._diff_preview_max_lines)
                diff_lines = diff.split("\n")
                if len(diff_lines) > max_lines:
                    diff_preview = "\n".join(diff_lines[:max_lines])
                    diff_preview += f"\n... (还有 {len(diff_lines) - max_lines} 行)"
                else:
                    diff_preview = diff
                
                # Render diff with syntax highlighting
                self.console.print()
                try:
                    syntax = Syntax(diff_preview, "diff", theme="monokai", line_numbers=False)
                    self.console.print(syntax)
                except Exception:
                    self.console.print(diff_preview)
                
                if len(diff_lines) > max_lines:
                    self.console.print("[dim]可选择 4 查看全部改动[/dim]")
                self.console.print()
            else:
                content_preview = metadata.get("content", "")[:300]
                if content_preview:
                    self.console.print("[bold yellow]内容预览:[/bold yellow]")
                    self.console.print(Panel(content_preview + "...", border_style="dim"))
                    self.console.print()
        
        elif permission_type == "bash":
            command = metadata.get("command", "unknown")
            self.console.print(f"[bold cyan]操作类型:[/bold cyan] Bash命令执行")
            self.console.print()
            self.console.print("[bold yellow]待执行命令:[/bold yellow]")
            self.console.print(Panel(command, border_style="yellow", expand=False))
            self.console.print()
        
        elif permission_type == "bash_delete":
            command = metadata.get("command", "unknown")
            self.console.print(f"[bold cyan]操作类型:[/bold cyan] Bash命令执行")
            self.console.print()
            self.console.print("[bold red]⚠️  危险警告: 此命令包含删除操作![/bold red]")
            self.console.print()
            self.console.print("[bold yellow]待执行命令:[/bold yellow]")
            self.console.print(Panel(command, border_style="red", expand=False))
            self.console.print()
        
        self.console.print("─" * 80)
        self.console.print("[bold white]请选择操作:[/bold white]")
        self.console.print()
        self.console.print("  [bold green]1[/bold green] → 同意本次操作 [dim](允许这一次)[/dim]")
        self.console.print("  [bold blue]2[/bold blue] → 本session内一直同意 [dim](本次会话内不再询问)[/dim]")
        self.console.print("  [bold red]3[/bold red] → 拒绝操作 [dim](取消操作)[/dim]")
        if permission_type in ("write", "edit") and metadata.get("diff", ""):
            self.console.print("  [bold yellow]4[/bold yellow] → 查看全部改动 [dim](支持翻页)[/dim]")
        self.console.print()
        self.console.print("─" * 80)
        
        # Get user input
        while True:
            try:
                choices = ["1", "2", "3"]
                if permission_type in ("write", "edit") and metadata.get("diff", ""):
                    choices.append("4")
                choice = Prompt.ask(
                    "[bold]请输入选项[/bold]",
                    choices=choices,
                    default="1",
                    show_choices=False
                )
                break
            except (KeyboardInterrupt, EOFError):
                self.console.print("[yellow]操作已取消,默认拒绝[/yellow]")
                choice = "3"
                break
        
        # If user wants to view all changes, enter pager mode
        if choice == "4":
            diff_lines = metadata.get("diff", "").split("\n")
            page_size = max(1, self._diff_page_max_lines)
            
            total_pages = max(1, (len(diff_lines) + page_size - 1) // page_size)
            page_index = 0
            
            while True:
                start = page_index * page_size
                end = start + page_size
                diff_page = "\n".join(diff_lines[start:end])
                
                self.console.print()
                self.console.print("─" * 80)
                self.console.print(f"[bold yellow]全部改动 (第 {page_index + 1}/{total_pages} 页)[/bold yellow]")
                self.console.print("─" * 80)
                self.console.print()
                try:
                    syntax = Syntax(diff_page, "diff", theme="monokai", line_numbers=False)
                    self.console.print(syntax)
                except Exception:
                    self.console.print(diff_page)
                
                self.console.print()
                self.console.print("[bold white]请选择操作:[/bold white]")
                self.console.print()
                self.console.print("  [bold green]1[/bold green] → 同意本次操作 [dim](允许这一次)[/dim]")
                self.console.print("  [bold blue]2[/bold blue] → 本session内一直同意 [dim](本次会话内不再询问)[/dim]")
                self.console.print("  [bold red]3[/bold red] → 拒绝操作 [dim](取消操作)[/dim]")
                if total_pages > 1:
                    self.console.print("  [bold yellow]4[/bold yellow] → 上一页 [dim](向前翻页)[/dim]")
                    self.console.print("  [bold yellow]5[/bold yellow] → 下一页 [dim](向后翻页)[/dim]")
                    pager_choices = ["1", "2", "3", "4", "5"]
                else:
                    pager_choices = ["1", "2", "3"]
                self.console.print()
                self.console.print("─" * 80)
                
                try:
                    pager_choice = Prompt.ask(
                        "[bold]请输入选项[/bold]",
                        choices=pager_choices,
                        default="1",
                        show_choices=False
                    )
                except (KeyboardInterrupt, EOFError):
                    self.console.print("[yellow]操作已取消,默认拒绝[/yellow]")
                    pager_choice = "3"
                
                if pager_choice in ("1", "2", "3"):
                    choice = pager_choice
                    break
                if pager_choice == "4":
                    page_index = max(0, page_index - 1)
                    continue
                if pager_choice == "5":
                    page_index = min(total_pages - 1, page_index + 1)
                    continue
            
        # Show confirmation
        self.console.print()
        if choice == "1":
            self.console.print("[green]✓ 已同意本次操作[/green]")
            result = ("once", None)
        elif choice == "2":
            self.console.print("[blue]✓ 已设置session权限,后续操作将自动允许[/blue]")
            result = ("always", None)
        else:
            # User rejected - ask for reason
            self.console.print("[red]✗ 操作已被拒绝[/red]")
            self.console.print()
            
            try:
                reason = Prompt.ask(
                    "[yellow]请输入拒绝理由(可选,按Enter跳过)[/yellow]",
                    default=""
                )
                if reason.strip():
                    # 用户提供了理由
                    result = ("reject", reason.strip())
                else:
                    # 用户未提供理由（直接按Enter）- 返回None触发回退
                    result = ("reject", None)
            except (KeyboardInterrupt, EOFError):
                # 用户Ctrl+C取消 - 也视为未提供理由
                result = ("reject", None)
        
        self.console.print("=" * 80)
        self.console.print()
        
        return result

    def show_reconnect_dialog(self, error_message: str = "") -> str:
        """
        Show reconnect dialog and get user choice.
        
        Args:
            error_message: Connection error message (optional)
        
        Returns:
            "1" to retry reconnect, "2" to stop and wait.
        """
        self.console.print()
        self.console.print("=" * 80)
        self.console.print("[bold yellow]⚠️  连接断开[/bold yellow]", justify="center")
        self.console.print("=" * 80)
        self.console.print()
        
        if error_message:
            self.console.print(f"[bold cyan]错误信息:[/bold cyan] {error_message}")
            self.console.print()
        
        self.console.print("─" * 80)
        self.console.print("[bold white]请选择操作:[/bold white]")
        self.console.print()
        self.console.print("  [bold green]1[/bold green] → 重新连接 [dim](继续尝试)[/dim]")
        self.console.print("  [bold red]2[/bold red] → 暂停等待 [dim](保留当前消息)[/dim]")
        self.console.print()
        self.console.print("─" * 80)
        
        # Get user input
        while True:
            try:
                choice = Prompt.ask(
                    "[bold]请输入选项[/bold]",
                    choices=["1", "2"],
                    default="1",
                    show_choices=False
                )
                break
            except (KeyboardInterrupt, EOFError):
                self.console.print("[yellow]操作已取消,默认暂停[/yellow]")
                choice = "2"
                break
        
        self.console.print("=" * 80)
        self.console.print()
        
        return choice
    
    def show_permission_status(self, permissions: Dict[str, bool]) -> None:
        """
        Show current permission status.
        
        Args:
            permissions: Dictionary of permission types and their status
        """
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("权限类型", style="cyan")
        table.add_column("状态")
        
        permission_names = {
            "write": "文件写入",
            "edit": "文件编辑",
            "bash": "Bash命令",
            "bash_delete": "Bash删除命令",
        }
        
        for perm_type, granted in permissions.items():
            name = permission_names.get(perm_type, perm_type)
            status = "[green]已授权[/green]" if granted else "[dim]未授权[/dim]"
            table.add_row(name, status)
        
        self.console.print()
        self.console.print(Panel(table, title="[bold]Session权限状态[/bold]", border_style="cyan"))
        self.console.print()
