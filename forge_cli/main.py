"""
MCP Forge CLI
─────────────
Install:   uv tool install mcp-forge   |   pipx install mcp-forge
Usage:     forge <command>

Commands:
  connect    Configure and test connection to a running MCP Forge instance
  status     Show server status and project list
  analyze    Trigger analysis on a project
  generate   Generate MCP server code for a project
  chat       Chat with the AI agent for a project
  logs       Tail live logs for a project
  plugin     Install/uninstall the Claude Desktop plugin config
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import httpx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

app = typer.Typer(
    name="forge",
    help="MCP Forge — convert any app into an MCP server",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
console = Console()

# ── Config helpers ─────────────────────────────────────────────────────────────

_CONFIG_FILE = Path.home() / ".mcp-forge" / "config.json"


def _load_config() -> dict:
    if _CONFIG_FILE.exists():
        return json.loads(_CONFIG_FILE.read_text())
    return {}


def _save_config(cfg: dict) -> None:
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def _get_base_url() -> str:
    cfg = _load_config()
    url = cfg.get("url") or os.getenv("FORGE_URL", "http://localhost:8000")
    return url.rstrip("/")


def _get_token() -> str:
    cfg = _load_config()
    return cfg.get("token") or os.getenv("FORGE_TOKEN", "")


def _client() -> httpx.Client:
    token = _get_token()
    headers = {"X-MCP-Token": token} if token else {}
    return httpx.Client(base_url=_get_base_url(), headers=headers, timeout=30)


# ── Commands ───────────────────────────────────────────────────────────────────

@app.command()
def connect(
    url: str = typer.Option("http://localhost:8000", "--url", "-u", help="MCP Forge base URL"),
    token: str = typer.Option("", "--token", "-t", help="MCP Auth Token (MCP_AUTH_TOKEN)"),
):
    """Configure connection to a running MCP Forge instance and verify it works."""
    console.print(f"[cyan]Connecting to MCP Forge at[/cyan] {url} …")
    try:
        with httpx.Client(base_url=url, headers={"X-MCP-Token": token} if token else {}, timeout=10) as c:
            r = c.get("/api/projects/")
            r.raise_for_status()
    except Exception as e:
        console.print(f"[red]✗ Connection failed:[/red] {e}")
        raise typer.Exit(1)

    _save_config({"url": url, "token": token})
    console.print(f"[green]✓ Connected![/green] Config saved to {_CONFIG_FILE}")
    console.print(f"  Projects found: {len(r.json())}")


@app.command()
def status():
    """Show MCP Forge server status and list all projects."""
    try:
        with _client() as c:
            projects = c.get("/api/projects/").raise_for_status().json()
    except Exception as e:
        console.print(f"[red]✗ Cannot reach MCP Forge:[/red] {e}")
        console.print(f"  Make sure the server is running: [bold]docker compose up -d[/bold]")
        console.print(f"  Then configure: [bold]forge connect --url http://localhost:8000 --token <token>[/bold]")
        raise typer.Exit(1)

    console.print(Panel(f"[green]● MCP Forge online[/green]  [dim]{_get_base_url()}[/dim]", expand=False))

    if not projects:
        console.print("[dim]No projects yet. Create one at http://localhost:8000 or via Claude.[/dim]")
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=4)
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Language")
    for p in projects:
        status_color = {"ready": "green", "analyzing": "yellow", "generating": "yellow",
                        "error": "red"}.get(p["status"], "white")
        table.add_row(str(p["id"]), p["name"],
                      f"[{status_color}]{p['status']}[/{status_color}]",
                      p.get("target_language") or "—")
    console.print(table)


@app.command()
def analyze(
    project_id: int = typer.Argument(..., help="Project ID to analyze"),
    source_url: Optional[str] = typer.Option(None, "--source", "-s", help="Override source URL"),
):
    """Trigger source analysis for a project."""
    params = {"source_url": source_url} if source_url else {}
    try:
        with _client() as c:
            r = c.post(f"/api/projects/{project_id}/analyze", params=params)
            r.raise_for_status()
    except Exception as e:
        console.print(f"[red]✗ Failed:[/red] {e}")
        raise typer.Exit(1)
    console.print(f"[green]✓ Analysis started[/green] for project {project_id}")
    console.print(f"  Watch progress: [bold]forge logs {project_id}[/bold]")


@app.command()
def generate(
    project_id: int = typer.Argument(..., help="Project ID to generate"),
    language: str = typer.Option("python_fastmcp", "--lang", "-l",
                                  help="Target: python_fastmcp | nodejs | go | generic"),
    label: str = typer.Option("", "--label", help="Snapshot label"),
):
    """Generate MCP server code for a project."""
    try:
        with _client() as c:
            r = c.post(f"/api/projects/{project_id}/generate/",
                       json={"target_language": language, "label": label})
            r.raise_for_status()
    except Exception as e:
        console.print(f"[red]✗ Failed:[/red] {e}")
        raise typer.Exit(1)
    console.print(f"[green]✓ Generation started[/green] (target: {language})")
    console.print(f"  Watch progress: [bold]forge logs {project_id}[/bold]")
    console.print(f"  View result at: [bold]{_get_base_url()}/projects/{project_id}[/bold]")


@app.command()
def chat(
    project_id: int = typer.Argument(..., help="Project ID"),
    message: str = typer.Argument(..., help="Message to send to the AI agent"),
):
    """Send a message to the AI agent for a project."""
    console.print(f"[dim]Sending to agent…[/dim]")
    try:
        with httpx.Client(base_url=_get_base_url(),
                          headers={"X-MCP-Token": _get_token()} if _get_token() else {},
                          timeout=120) as c:
            r = c.post(f"/api/projects/{project_id}/chat/send",
                       json={"content": message})
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        console.print(f"[red]✗ Failed:[/red] {e}")
        raise typer.Exit(1)

    console.print(Panel(data.get("response", ""), title="[cyan]Agent[/cyan]", expand=False))
    if data.get("clarifications"):
        console.print("[yellow]⚠ Agent needs clarification:[/yellow]")
        for cl in data["clarifications"]:
            console.print(f"  [yellow]?[/yellow] {cl['question']}")
        console.print(f"  Answer at: [bold]{_get_base_url()}/projects/{project_id}?tab=chat[/bold]")


@app.command()
def logs(
    project_id: int = typer.Argument(..., help="Project ID"),
    tail: int = typer.Option(50, "--tail", "-n", help="Number of recent log lines to show"),
):
    """Show recent logs for a project."""
    try:
        with _client() as c:
            r = c.get(f"/api/projects/{project_id}/logs", params={"limit": tail})
            r.raise_for_status()
            entries = r.json()
    except Exception as e:
        console.print(f"[red]✗ Failed:[/red] {e}")
        raise typer.Exit(1)

    level_colors = {"debug": "dim", "info": "blue", "warning": "yellow", "error": "red"}
    for entry in entries:
        color = level_colors.get(entry.get("level", "info"), "white")
        ts = entry.get("created_at", "")[:19].replace("T", " ")
        src = f"[dim][{entry.get('source', '')}][/dim] " if entry.get("source") else ""
        console.print(f"[dim]{ts}[/dim] {src}[{color}]{entry.get('message', '')}[/{color}]")


@app.command()
def plugin(
    action: str = typer.Argument(..., help="install | uninstall | status"),
    mode: str = typer.Option("sse", "--mode", "-m", help="sse | stdio"),
):
    """Install or remove the Claude Desktop plugin config."""
    import platform
    if platform.system() == "Windows":
        claude_dir = Path(os.environ["APPDATA"]) / "Claude"
    else:
        claude_dir = Path.home() / "Library" / "Application Support" / "Claude"

    config_path = claude_dir / "claude_desktop_config.json"

    if action == "status":
        if config_path.exists():
            console.print(f"[green]✓ Plugin config exists:[/green] {config_path}")
            data = json.loads(config_path.read_text())
            if "mcp-forge" in data.get("mcpServers", {}):
                console.print("[green]✓ mcp-forge server entry found[/green]")
            else:
                console.print("[yellow]⚠ mcp-forge entry missing from mcpServers[/yellow]")
        else:
            console.print(f"[red]✗ No config at {config_path}[/red]")
        return

    if action == "install":
        token = _get_token()
        if not token:
            token = typer.prompt("MCP Auth Token (from docker exec mcp_forge_app printenv MCP_AUTH_TOKEN)")

        if mode == "sse":
            server_cfg = {
                "url": "http://localhost:8001/sse",
                "headers": {"X-MCP-Token": token}
            }
        else:
            cwd = str(Path(__file__).parent.parent)
            server_cfg = {
                "command": "python",
                "args": ["mcp_server/server.py"],
                "cwd": cwd,
                "env": {
                    "PYTHONPATH": cwd,
                    "APP_URL": _get_base_url(),
                    "MCP_AUTH_TOKEN": token,
                    "MCP_TRANSPORT": "stdio",
                }
            }

        # Load existing config or start fresh
        claude_dir.mkdir(parents=True, exist_ok=True)
        existing = json.loads(config_path.read_text()) if config_path.exists() else {}
        existing.setdefault("mcpServers", {})["mcp-forge"] = server_cfg
        config_path.write_text(json.dumps(existing, indent=2))

        console.print(f"[green]✓ Plugin installed![/green] Config written to:")
        console.print(f"  {config_path}")
        console.print(f"\n[bold]Next step:[/bold] Fully quit and reopen Claude Desktop.")
        console.print(f"Then go to [bold]Settings → Developer[/bold] to verify mcp-forge is listed.")

    elif action == "uninstall":
        if not config_path.exists():
            console.print("[yellow]No config file found — nothing to remove.[/yellow]")
            return
        data = json.loads(config_path.read_text())
        if "mcp-forge" in data.get("mcpServers", {}):
            del data["mcpServers"]["mcp-forge"]
            config_path.write_text(json.dumps(data, indent=2))
            console.print(f"[green]✓ mcp-forge removed from {config_path}[/green]")
        else:
            console.print("[yellow]mcp-forge not found in config — nothing to remove.[/yellow]")

    else:
        console.print(f"[red]Unknown action: {action}[/red]  Use: install | uninstall | status")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
