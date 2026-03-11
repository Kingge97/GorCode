"""
CLI Main Entry
==============

Main entry point for GorCode CLI using Click.
"""

import sys
import os
import json
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

# Add repo root and GorCode dir to path for imports
_repo_root = Path(__file__).resolve().parent.parent.parent.parent
_gorcode_dir = _repo_root / "GorCode"
for _p in (str(_repo_root), str(_gorcode_dir)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backend.core.events import EventBus, Event, EventType
from backend.core.executor import BackendExecutor
from backend.config.manager import ConfigManager, GorCodeConfig
from frontend.ui.renderer import UIRenderer
from frontend.commands.handler import CommandHandler


# Create console instance
console = Console()


def get_version() -> str:
    """Get GorCode version."""
    try:
        from GorCode import __version__
        return __version__
    except ImportError:
        return "0.1.0"


def print_welcome():
    """Print welcome message."""
    version = get_version()
    
    title = Text()
    title.append("GorCode", style="bold cyan")
    title.append(f" v{version}", style="dim")
    
    subtitle_plain = "AI-Powered CLI"
    subtitle = f"[italic dim]{subtitle_plain}[/]"
    # Ensure the title renderable is wide enough for the subtitle on the border.
    pad_needed = max(0, (len(subtitle_plain) + 1) - len(title.plain))
    if pad_needed:
        title.append(" " * pad_needed)
    
    console.print()
    console.print(Panel(
        title,
        subtitle=subtitle,
        border_style="cyan",
        expand=False,
    ))
    console.print()
    console.print("[dim]Type[/dim] [bold]/help[/bold] [dim]for available commands, or start chatting.[/dim]")
    console.print("[dim]Press[/dim] [bold]Ctrl+C[/bold] [dim]to exit.[/dim]")
    console.print()


def print_goodbye():
    """Print goodbye message."""
    console.print()
    console.print("[dim]Goodbye! Thank you for using GorCode.[/dim]")
    console.print()


def _has_valid_model_connections(config: GorCodeConfig) -> bool:
    """Check if config contains at least one usable model connection."""
    if not config.model_connections:
        return False
    for conn in config.model_connections.values():
        if not conn:
            continue
        api_key = (conn.api_key or "").strip()
        base_url = (conn.base_url or "").strip()
        model_name = (conn.model_name or "").strip()
        if api_key and api_key != "YOUR_API_KEY_HERE" and base_url and model_name:
            return True
    return False


def _ensure_user_config_ready(config_manager: ConfigManager) -> bool:
    """Ensure user config exists and has usable connections before startup."""
    user_config_path = config_manager.get_user_config_path()
    if not user_config_path.exists():
        console.print("[yellow]User config not found. Creating default config...[/yellow]")
        created = config_manager.initialize_user_config()
        if not created:
            console.print("[red]Failed to create default user config:[/red]")
            console.print(f"[dim]{user_config_path}[/dim]")
            console.print("[dim]Please create and configure it, then restart GorCode.[/dim]")
            return False
        console.print("[green]Default user config created:[/green]")
        console.print(f"[dim]{user_config_path}[/dim]")
        console.print("[dim]Please configure your connections and restart GorCode.[/dim]")
        return False
    try:
        with open(user_config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        user_config = GorCodeConfig.from_dict(data)
    except (json.JSONDecodeError, OSError) as e:
        console.print("[red]Failed to read user config:[/red]")
        console.print(f"[dim]{user_config_path}[/dim]")
        console.print(f"[dim]Error: {e}[/dim]")
        console.print("[dim]Please fix the config and restart GorCode.[/dim]")
        return False
    if not _has_valid_model_connections(user_config):
        console.print("[yellow]No usable model connections found[/yellow]")
        console.print(f"[dim]Please configure at least one connection in {user_config_path} and restart GorCode.[/dim]")
        return False
    return True


@click.group(invoke_without_command=True)
@click.option("--version", "-v", is_flag=True, help="Show version and exit")
@click.option("--debug", "-d", is_flag=True, help="Enable debug mode")
@click.option("--config", "-c", type=click.Path(), help="Path to config file")
@click.option("--agent", "-a", type=str, default=None, help="Default agent to use (overrides config)")
@click.option("--model", "-m", type=str, help="Model connection name to use")
@click.option("--prompt", "-p", type=str, help="Run a single prompt and exit")
@click.option(
    "--mcps",
    multiple=True,
    help="Run MCP command(s) before prompt/REPL (same syntax as /mcps)",
)
@click.option(
    "--permission",
    type=click.Choice(["ask", "all", "exceptrm"], case_sensitive=False),
    default="ask",
    show_default=True,
    help="Permission profile (ask/all/exceptrm)",
)
@click.pass_context
def cli(
    ctx: click.Context,
    version: bool,
    debug: bool,
    config: Optional[str],
    agent: Optional[str],
    model: Optional[str],
    prompt: Optional[str],
    mcps: tuple,
    permission: str,
):
    """
    GorCode - AI-Powered CLI Coding Assistant
    
    A ClaudeCode/Codex/OpenCode-like CLI product with frontend-backend separation.
    """
    if version:
        console.print(f"GorCode v{get_version()}")
        return
    
    if ctx.invoked_subcommand is None:
        # Run interactive mode
        ctx.invoke(
            run,
            debug=debug,
            config_path=config,
            agent=agent,
            model=model,
            prompt=prompt,
            mcps=mcps,
            permission=permission,
        )


@cli.command()
@click.option("--debug", "-d", is_flag=True, help="Enable debug mode")
@click.option("--config-path", "-c", type=click.Path(), help="Path to config file")
@click.option("--agent", "-a", type=str, default=None, help="Default agent to use (overrides config)")
@click.option("--model", "-m", type=str, help="Model connection name to use")
@click.option("--prompt", "-p", type=str, help="Run a single prompt and exit")
@click.option(
    "--mcps",
    multiple=True,
    help="Run MCP command(s) before prompt/REPL (same syntax as /mcps)",
)
@click.option(
    "--permission",
    type=click.Choice(["ask", "all", "exceptrm"], case_sensitive=False),
    default="ask",
    show_default=True,
    help="Permission profile (ask/all/exceptrm)",
)
def run(
    debug: bool,
    config_path: Optional[str],
    agent: Optional[str],
    model: Optional[str],
    prompt: Optional[str],
    mcps: tuple,
    permission: str,
):
    """Run GorCode in interactive mode."""
    config_manager = ConfigManager(config_path=config_path)
    if not _ensure_user_config_ready(config_manager):
        return
    print_welcome()
    
    # Initialize components
    event_bus = EventBus()
    executor = BackendExecutor(event_bus)
    
    # 订阅 EventBus 事件，让渲染器能接收子代理等事件
    # 子代理的事件通过 EventBus 发送，主代理的事件通过 yield 返回
    def setup_event_subscriptions():
        """Setup event subscriptions for the renderer."""
        # 订阅子代理启动/结束事件
        event_bus.subscribe(EventType.AGENT_SUBAGENT_START, ui_renderer.render_event)
        event_bus.subscribe(EventType.AGENT_SUBAGENT_END, ui_renderer.render_event)
        # 订阅子代理的工具事件
        event_bus.subscribe(EventType.TOOL_EXECUTION_START, ui_renderer.render_event)
        event_bus.subscribe(EventType.TOOL_RESULT, ui_renderer.render_event)
        # 订阅子代理的发言事件
        event_bus.subscribe(EventType.MODEL_ANSWER, ui_renderer.render_event)
        # 订阅子代理的 UI 消息事件（如压缩提示）
        event_bus.subscribe(EventType.UI_MESSAGE, ui_renderer.render_event)
    
    config = config_manager.load_config()
    # If --agent not provided, fall back to config default_agent
    agent = agent or config.default_agent or "build"
    if debug:
        config.debug_mode = True
    
    ui_renderer = UIRenderer(console, config)
    setup_event_subscriptions()
    
    # Initialize executor with components
    from backend.tools import initialize_tools
    from backend.agents.base import AgentRegistry
    
    tool_registry = initialize_tools(config.default_encoding)
    agent_registry = AgentRegistry()
    
    executor.initialize(
        config_manager=config_manager,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
    )
    
    # Set permission callback for UI interaction
    def permission_callback(permission_type: str, metadata: dict) -> tuple:
        """
        Permission callback for UI interaction.
        
        Args:
            permission_type: Type of permission (write, edit, bash, bash_delete)
            metadata: Permission metadata
            
        Returns:
            Tuple of (response, reason):
            - response: 'once', 'always', or 'reject'
            - reason: Rejection reason (None if not rejected)
        """
        return ui_renderer.show_permission_dialog(permission_type, metadata)
    
    executor.set_permission_callback(permission_callback)

    # Apply permission profile (session-level)
    if permission and permission.lower() != "ask":
        from backend.permission import get_permission_manager, PermissionType

        permission_manager = get_permission_manager()
        permission_value = permission.lower()
        if permission_value in ("all", "exceptrm"):
            permission_manager.grant_session_permission(PermissionType.WRITE)
            permission_manager.grant_session_permission(PermissionType.EDIT)
            permission_manager.grant_session_permission(PermissionType.BASH)
            if permission_value == "all":
                permission_manager.grant_session_permission(PermissionType.BASH_DELETE)

    def reconnect_callback(error_message: str) -> str:
        """
        Reconnect callback for UI interaction.
        
        Args:
            error_message: Connection error message (optional)
        
        Returns:
            "1" to retry reconnect, "2" to stop and wait.
        """
        return ui_renderer.show_reconnect_dialog(error_message)
    
    executor.set_reconnect_callback(reconnect_callback)
    
    command_handler = CommandHandler(executor, config_manager, ui_renderer)

    # Run MCP commands from CLI before prompt/REPL
    if mcps:
        for mcp_cmd in mcps:
            cmd = (mcp_cmd or "").strip()
            if not cmd:
                continue
            if cmd.startswith("/"):
                command = cmd
            elif cmd.lower().startswith("mcps"):
                command = f"/{cmd}"
            else:
                command = f"/mcps {cmd}"
            command_handler.handle(command)
    
    # Try to switch to default agent (this will use agent_model_mapping to select the correct model)
    if agent_registry.get(agent):
        if not executor.switch_agent(agent):
            # Fallback: if agent switch fails, try to connect to first available model
            if config.model_connections:
                first_model = list(config.model_connections.keys())[0]
                if not executor.switch_model(first_model):
                    console.print(f"[yellow]Warning: Failed to connect to model '{first_model}'[/yellow]")
                    console.print("[dim]Check your API key and base_url in ~/.gorcode/config.json[/dim]")
            else:
                console.print("[yellow]Warning: No model connections configured[/yellow]")
                console.print("[dim]Please configure models in ~/.gorcode/config.json[/dim]")
    else:
        # Agent not found in registry, fallback to old behavior
        executor.state.current_agent = agent
        if config.model_connections:
            first_model = list(config.model_connections.keys())[0]
            if not executor.switch_model(first_model):
                console.print(f"[yellow]Warning: Failed to connect to model '{first_model}'[/yellow]")
                console.print("[dim]Check your API key and base_url in ~/.gorcode/config.json[/dim]")
        else:
            console.print("[yellow]Warning: No model connections configured[/yellow]")
            console.print("[dim]Please configure models in ~/.gorcode/config.json[/dim]")
    
    # Override model if explicitly specified
    if model:
        if not executor.switch_model(model):
            console.print(f"[yellow]Warning: Failed to connect to model '{model}'[/yellow]")

    # If a prompt is provided, run once and exit (non-interactive)
    if prompt:
        for event in executor.process_user_input(prompt):
            ui_renderer.render_event(event)
        print_goodbye()
        return

    # Setup history
    history_dir = Path.home() / ".gorcode"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_file = history_dir / "history"
    
    session = PromptSession(
        history=FileHistory(str(history_file)),
        auto_suggest=AutoSuggestFromHistory(),
    )
    
    # Main REPL loop
    while True:
        try:
            # Get user input
            user_input = session.prompt(
                f"[{executor.state.current_agent}]> ",
                multiline=False,
            ).strip()
            
            if not user_input:
                continue
            
            # Handle commands
            if user_input.startswith("/"):
                should_continue = command_handler.handle(user_input)
                if not should_continue:
                    break
                continue
            
            # Process regular input
            for event in executor.process_user_input(user_input):
                ui_renderer.render_event(event)
            
        except KeyboardInterrupt:
            # Handle Ctrl+C
            console.print()
            if click.confirm("Exit GorCode?", default=True):
                break
            continue
        
        except EOFError:
            # Handle Ctrl+D
            console.print()
            break
        
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            if debug:
                import traceback
                traceback.print_exc()
    
    print_goodbye()


@cli.command()
@click.argument("path", type=click.Path(), default=".")
@click.option("--force", "-f", is_flag=True, help="Force overwrite existing configuration")
@click.option("--user-only", is_flag=True, help="Initialize user config only")
@click.option("--project-only", is_flag=True, help="Initialize project config only")
def init(path: str, force: bool, user_only: bool, project_only: bool):
    """Initialize GorCode in the current or specified directory."""
    from backend.config.initializer import ProjectInitializer
    
    project_path = Path(path).resolve()
    
    console.print()
    console.print(f"[bold]Initializing GorCode[/bold]")
    console.print(f"Project path: [cyan]{project_path}[/cyan]")
    console.print()
    
    initializer = ProjectInitializer(project_path=str(project_path))
    
    if user_only:
        result = initializer.initialize_user_config(force=force)
        if result.success:
            console.print(f"[green]✓ User configuration: {result.message}[/green]")
            for p in result.created_paths:
                console.print(f"  [dim]Created: {p}[/dim]")
        else:
            console.print(f"[red]✗ User configuration: {result.message}[/red]")
            for e in result.errors:
                console.print(f"  [dim]Error: {e}[/dim]")
    
    elif project_only:
        result = initializer.initialize_project_config(force=force)
        if result.success:
            console.print(f"[green]✓ Project configuration: {result.message}[/green]")
            for p in result.created_paths:
                console.print(f"  [dim]Created: {p}[/dim]")
        else:
            console.print(f"[red]✗ Project configuration: {result.message}[/red]")
            for e in result.errors:
                console.print(f"  [dim]Error: {e}[/dim]")
    
    else:
        results = initializer.initialize_all(force=force)
        
        for name, result in [("User", results["user"]), ("Project", results["project"])]:
            if result.success:
                console.print(f"[green]✓ {name} configuration: {result.message}[/green]")
                for p in result.created_paths:
                    console.print(f"  [dim]Created: {p}[/dim]")
            else:
                console.print(f"[red]✗ {name} configuration: {result.message}[/red]")
                for e in result.errors:
                    console.print(f"  [dim]Error: {e}[/dim]")
    
    console.print()
    console.print("[dim]Next steps:[/dim]")
    console.print("[dim]1. Edit[/dim] [cyan]~/.gorcode/config.json[/cyan] [dim]to add your API keys[/dim]")
    console.print(f"[dim]2. Run[/dim] [cyan]gorcode[/cyan] [dim]in {project_path}[/dim]")


@cli.command("status")
@click.option("--config", "-c", type=click.Path(), help="Path to config file")
def status_cmd(config: Optional[str]):
    """Show configuration and connection status."""
    config_manager = ConfigManager(config_path=config)
    
    console.print()
    console.print("[bold]GorCode Status[/bold]")
    console.print()
    
    # Configuration info
    info = config_manager.get_config_info()
    
    console.print("[bold]Configuration:[/bold]")
    console.print(f"  User config: [cyan]{info['user_config']['path']}[/cyan]")
    console.print(f"    Exists: [green]Yes[/green]" if info['user_config']['exists'] else "    Exists: [red]No[/red]")
    
    console.print(f"  Project config: [cyan]{info['project_config']['path']}[/cyan]")
    console.print(f"    Exists: [green]Yes[/green]" if info['project_config']['exists'] else "    Exists: [red]No[/red]")
    
    if info['custom_config']['path']:
        console.print(f"  Custom config: [cyan]{info['custom_config']['path']}[/cyan]")
        console.print(f"    Exists: [green]Yes[/green]" if info['custom_config']['exists'] else "    Exists: [red]No[/red]")
    
    console.print()
    
    # Model connections
    console.print("[bold]Model Connections:[/bold]")
    models = config_manager.list_available_models()
    if models:
        for model in models:
            conn = config_manager.get_model_connection(model)
            console.print(f"  [cyan]{model}[/cyan]: {conn.model_name} ({conn.router})")
    else:
        console.print("  [dim]No model connections configured[/dim]")
    
    console.print()
    
    # Agent model mapping
    console.print("[bold]Agent Model Mapping:[/bold]")
    mapping = info['merged_config']['agent_model_mapping']
    for agent, model in mapping.items():
        console.print(f"  [cyan]{agent}[/cyan] → [yellow]{model}[/yellow]")
    
    console.print()


@cli.command("list-agents")
def list_agents():
    """List all available agents."""
    from backend.agents.base import AgentRegistry
    
    registry = AgentRegistry()
    
    console.print("[bold]Available Agents:[/bold]")
    console.print()
    
    for agent in registry.get_all_agents():
        status = "[dim](hidden)[/dim]" if agent.is_hidden else ""
        default = "[green](default)[/green]" if agent.is_default else ""
        mode = f"[yellow][{agent.mode.value}][/yellow]"
        
        console.print(f"  [cyan]{agent.name}[/cyan] {mode} {default}{status}")
        if agent.description:
            console.print(f"    [dim]{agent.description}[/dim]")
        console.print()


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
