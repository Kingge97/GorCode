"""
CLI Main Entry
==============

Main entry point for GorCode CLI using Click.
"""

from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

from types import SimpleNamespace

from GorCode.frontend.ui.renderer import UIRenderer
from GorCode.frontend.ui.init_render import render_init_result
from GorCode.frontend.commands.handler import CommandHandler
from GorCode.bridge.inprocess import FrontendClient, create_inprocess_client


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


def _get_current_agent(client: FrontendClient) -> str:
    """Get current agent name for prompt display."""
    resp = client.request("session.status")
    if resp.get("success"):
        return resp.get("payload", {}).get("agent") or "build"
    return "build"


def _has_valid_model_connections(config: dict) -> bool:
    """Check if config contains at least one usable model connection."""
    model_connections = config.get("model_connections") if isinstance(config, dict) else None
    if not model_connections:
        return False
    for conn in model_connections.values():
        if not isinstance(conn, dict):
            continue
        api_key = (conn.get("api_key") or "").strip()
        base_url = (conn.get("base_url") or "").strip()
        model_name = (conn.get("model_name") or "").strip()
        if api_key and api_key != "YOUR_API_KEY_HERE" and base_url and model_name:
            return True
    return False


def _ensure_user_config_ready(client: FrontendClient) -> bool:
    """Ensure user config exists and has usable connections before startup."""
    status = client.request("config.status")
    if not status.get("success"):
        console.print("[red]Failed to read configuration status.[/red]")
        return False

    payload = status.get("payload", {})
    user_exists = payload.get("user_exists", False)
    user_path = payload.get("paths", {}).get("user", "~/.gorcode/config.json")

    if not user_exists:
        console.print("[yellow]User config not found. Creating default config...[/yellow]")
        created = client.request("config.initialize", {"user_only": True, "force": False})
        result = created.get("payload", {}).get("result", {}) if created.get("success") else {}
        if not created.get("success") or not result.get("success"):
            console.print("[red]Failed to create default user config:[/red]")
            console.print(f"[dim]{user_path}[/dim]")
            console.print("[dim]Please create and configure it, then restart GorCode.[/dim]")
            return False
        console.print("[green]Default user config created:[/green]")
        console.print(f"[dim]{user_path}[/dim]")
        console.print("[dim]Please configure your connections and restart GorCode.[/dim]")
        return False

    user_config_resp = client.request("config.get", {"scope": "user"})
    if not user_config_resp.get("success"):
        console.print("[red]Failed to read user config:[/red]")
        console.print(f"[dim]{user_path}[/dim]")
        console.print(f"[dim]Error: {user_config_resp.get('error', 'unknown')}[/dim]")
        console.print("[dim]Please fix the config and restart GorCode.[/dim]")
        return False

    merged_resp = client.request("config.get", {"scope": "merged"})
    merged_config = merged_resp.get("payload", {}).get("config", {}) if merged_resp.get("success") else {}
    if not _has_valid_model_connections(merged_config):
        console.print("[yellow]No usable model connections found[/yellow]")
        console.print(f"[dim]Please configure at least one connection in {user_path} and restart GorCode.[/dim]")
        return False

    return True


def _connect_first_model_or_warn(config: dict, client: FrontendClient) -> None:
    """Connect to the first configured model, or warn if unavailable."""
    model_connections = config.get("model_connections") if isinstance(config, dict) else None
    if model_connections:
        first_model = list(model_connections.keys())[0]
        if not client.request("model.switch", {"model": first_model}).get("success"):
            console.print(f"[yellow]Warning: Failed to connect to model '{first_model}'[/yellow]")
            console.print("[dim]Check your API key and base_url in ~/.gorcode/config.json[/dim]")
    else:
        console.print("[yellow]Warning: No model connections configured[/yellow]")
        console.print("[dim]Please configure models in ~/.gorcode/config.json[/dim]")


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
    runtime = create_inprocess_client(config_path=config_path)
    client = runtime.client

    if not _ensure_user_config_ready(client):
        return
    print_welcome()
    
    # Initialize components
    config_resp = client.request("config.get", {"scope": "merged"})
    config = config_resp.get("payload", {}).get("config", {}) if config_resp.get("success") else {}
    # If --agent not provided, fall back to config default_agent
    agent = agent or config.get("default_agent") or "build"

    if debug:
        client.request("debug.set", {"enabled": True})
    
    ui_renderer = UIRenderer(console, SimpleNamespace(**config))
    
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
    
    client.set_permission_callback(permission_callback)

    # Apply permission profile (session-level)
    if permission and permission.lower() != "ask":
        permission_value = permission.lower()
        if permission_value in ("all", "exceptrm"):
            client.request("permission.grant", {"type": "write"})
            client.request("permission.grant", {"type": "edit"})
            client.request("permission.grant", {"type": "bash"})
            if permission_value == "all":
                client.request("permission.grant", {"type": "bash_delete"})

    def reconnect_callback(error_message: str) -> str:
        """
        Reconnect callback for UI interaction.
        
        Args:
            error_message: Connection error message (optional)
        
        Returns:
            "1" to retry reconnect, "2" to stop and wait.
        """
        return ui_renderer.show_reconnect_dialog(error_message)
    
    client.set_reconnect_callback(reconnect_callback)

    # Sync backend debug mode with config
    if config.get("debug_mode"):
        client.request("debug.set", {"enabled": True})

    command_handler = CommandHandler(client, ui_renderer)

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
    agent_exists = client.request("agent.get", {"name": agent}).get("success")
    if agent_exists:
        agent_resp = client.request("agent.switch", {"name": agent})
        if not agent_resp.get("success"):
            # Fallback: if agent switch fails, try to connect to first available model
            _connect_first_model_or_warn(config, client)
    else:
        # Agent not found in registry, fallback to old behavior
        client.request("agent.set", {"agent": agent})
        _connect_first_model_or_warn(config, client)
    
    # Override model if explicitly specified
    if model:
        if not client.request("model.switch", {"model": model}).get("success"):
            console.print(f"[yellow]Warning: Failed to connect to model '{model}'[/yellow]")

    # If a prompt is provided, run once and exit (non-interactive)
    if prompt:
        for event in client.stream("chat.send", {"text": prompt}):
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
                f"[{_get_current_agent(client)}]> ",
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
            for event in client.stream("chat.send", {"text": user_input}):
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
    project_path = Path(path).resolve()
    
    console.print()
    console.print(f"[bold]Initializing GorCode[/bold]")
    console.print(f"Project path: [cyan]{project_path}[/cyan]")
    console.print()
    
    ui_renderer = UIRenderer(console)
    runtime = create_inprocess_client()
    client = runtime.client

    payload = {
        "path": str(project_path),
        "force": force,
        "user_only": user_only,
        "project_only": project_only,
    }
    response = client.request("config.initialize", payload)
    if not response.get("success"):
        ui_renderer.print_error(response.get("error") or "Failed to initialize config")
        return

    data = response.get("payload", {})
    if user_only:
        render_init_result(ui_renderer, "User", data.get("result", {}))
    elif project_only:
        render_init_result(ui_renderer, "Project", data.get("result", {}))
    else:
        results = data.get("results", {})
        for name, result in [("User", results.get("user", {})), ("Project", results.get("project", {}))]:
            render_init_result(ui_renderer, name, result)
    
    console.print()
    console.print("[dim]Next steps:[/dim]")
    console.print("[dim]1. Edit[/dim] [cyan]~/.gorcode/config.json[/cyan] [dim]to add your API keys[/dim]")
    console.print(f"[dim]2. Run[/dim] [cyan]gorcode[/cyan] [dim]in {project_path}[/dim]")


@cli.command("status")
@click.option("--config", "-c", type=click.Path(), help="Path to config file")
def status_cmd(config: Optional[str]):
    """Show configuration and connection status."""
    console.print()
    console.print("[bold]GorCode Status[/bold]")
    console.print()
    runtime = create_inprocess_client(config_path=config)
    client = runtime.client

    status = client.request("config.status")
    info = status.get("payload", {}) if status.get("success") else {}

    console.print("[bold]Configuration:[/bold]")
    user_path = info.get("paths", {}).get("user", "~/.gorcode/config.json")
    project_path = info.get("paths", {}).get("project", "./.gorcode/config.json")
    console.print(f"  User config: [cyan]{user_path}[/cyan]")
    console.print(f"    Exists: [green]Yes[/green]" if info.get("user_exists") else "    Exists: [red]No[/red]")

    console.print(f"  Project config: [cyan]{project_path}[/cyan]")
    console.print(f"    Exists: [green]Yes[/green]" if info.get("project_exists") else "    Exists: [red]No[/red]")

    custom_path = info.get("paths", {}).get("custom")
    if custom_path:
        console.print(f"  Custom config: [cyan]{custom_path}[/cyan]")

    console.print()

    config_resp = client.request("config.get", {"scope": "merged"})
    merged = config_resp.get("payload", {}).get("config", {}) if config_resp.get("success") else {}

    console.print("[bold]Model Connections:[/bold]")
    models = merged.get("model_connections", {})
    if models:
        for name, conn in models.items():
            model_name = conn.get("model_name", "unknown") if isinstance(conn, dict) else "unknown"
            router = conn.get("router", "unknown") if isinstance(conn, dict) else "unknown"
            console.print(f"  [cyan]{name}[/cyan]: {model_name} ({router})")
    else:
        console.print("  [dim]No model connections configured[/dim]")

    console.print()

    console.print("[bold]Agent Model Mapping:[/bold]")
    mapping = merged.get("agent_model_mapping", {})
    for agent, model in mapping.items():
        console.print(f"  [cyan]{agent}[/cyan] → [yellow]{model}[/yellow]")

    console.print()


@cli.command("list-agents")
def list_agents():
    """List all available agents."""
    console.print("[bold]Available Agents:[/bold]")
    console.print()

    runtime = create_inprocess_client()
    client = runtime.client
    response = client.request("agent.list", {"visibility": "all"})
    agents = response.get("payload", {}).get("agents", []) if response.get("success") else []

    for agent in agents:
        status = "[dim](hidden)[/dim]" if agent.get("is_hidden") else ""
        default = "[green](default)[/green]" if agent.get("is_default") else ""
        mode = f"[yellow][{agent.get('mode', 'unknown')}][/yellow]"

        console.print(f"  [cyan]{agent.get('name', 'unknown')}[/cyan] {mode} {default}{status}")
        if agent.get("description"):
            console.print(f"    [dim]{agent.get('description')}[/dim]")
        console.print()


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
