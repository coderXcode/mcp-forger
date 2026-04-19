"""
MCP Forge — FastMCP server.
Exposes all forge capabilities as MCP tools to Claude Desktop.
Run standalone: python mcp_server/server.py
Or served as ASGI via the main FastAPI app at /mcp.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add project root to path when run standalone
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastmcp import FastMCP

from config import settings

import os
# When running inside Docker, APP_URL should point to the app service
_APP_BASE = os.getenv("APP_URL", f"http://localhost:{settings.port}")

mcp = FastMCP(
    "MCP Forge",
    instructions=(
        "MCP Forge helps you convert any application into an MCP server. "
        "Use create_project to start, then analyze_source, generate_mcp, "
        "run_tests, and rollback_snapshot as needed. "
        "Use chat_with_agent to discuss changes with the AI assistant."
    ),
)


# ── Project Tools ─────────────────────────────────────────────────────────────

@mcp.tool()
async def create_project(
    name: str,
    source_url: str,
    source_type: str = "openapi",
    target_language: str = "python_fastmcp",
    description: str = "",
) -> str:
    """Create a new MCP conversion project.

    source_type: openapi | github | url | upload | manual
    target_language: python_fastmcp | nodejs | go | generic
    """
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_APP_BASE}/api/projects/",
            json={
                "name": name,
                "source_url": source_url,
                "source_type": source_type,
                "target_language": target_language,
                "description": description,
            },
            headers=_auth_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return f"Project '{name}' created (id={data['id']}, slug={data['slug']}). Analysis started automatically."


@mcp.tool()
async def list_projects() -> str:
    """List all MCP Forge projects with their current status."""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_APP_BASE}/api/projects/",
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        projects = resp.json()
        if not projects:
            return "No projects found."
        lines = ["Projects:"]
        for p in projects:
            lines.append(f"  [{p['id']}] {p['name']} — {p['status']} ({p['target_language']})")
        return "\n".join(lines)


@mcp.tool()
async def analyze_source(project_id: int, source_url: str | None = None) -> str:
    """Trigger source code / API analysis for a project.

    Optionally provide a new source_url to override the project's current source.
    """
    import httpx
    params = {}
    if source_url:
        params["source_url"] = source_url
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_APP_BASE}/api/projects/{project_id}/analyze",
            params=params,
            headers=_auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return f"Analysis started for project {project_id}. Check the dashboard for progress."


@mcp.tool()
async def generate_mcp(
    project_id: int,
    target_language: str = "python_fastmcp",
    label: str = "",
    description: str = "",
) -> str:
    """Generate MCP server code for a project.

    target_language: python_fastmcp | nodejs | go | generic
    Requires analysis to have been run first.
    """
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_APP_BASE}/api/projects/{project_id}/generate/",
            json={"target_language": target_language, "label": label, "description": description},
            headers=_auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return f"Generation started for project {project_id} (target: {target_language}). Check the dashboard for the generated code."


@mcp.tool()
async def get_generated_code(project_id: int) -> str:
    """Get the currently generated MCP code for a project."""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_APP_BASE}/api/projects/{project_id}/generate/files",
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        files = data.get("files", {})
        if not files:
            return "No generated code found. Run generate_mcp first."
        result = []
        for fname, content in files.items():
            result.append(f"### {fname}\n```\n{content[:3000]}\n```")
        return "\n\n".join(result)


@mcp.tool()
async def run_tests(project_id: int, regenerate_tests: bool = False) -> str:
    """Run tests for the generated MCP server.

    regenerate_tests: if True, the agent will generate new test cases before running.
    """
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_APP_BASE}/api/projects/{project_id}/tests/run",
            json={"regenerate_tests": regenerate_tests},
            headers=_auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return f"Test run started (run_id={data['run_id']}). Check the dashboard Tests tab for results."


@mcp.tool()
async def get_test_results(project_id: int) -> str:
    """Get the latest test run results for a project."""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_APP_BASE}/api/projects/{project_id}/tests/runs",
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        runs = resp.json()
        if not runs:
            return "No test runs found."
        last = runs[0]
        lines = [
            f"Latest test run (#{last['id']}): {last['status']}",
            f"  Passed: {last['passed']}/{last['total']}",
            f"  Failed: {last['failed']}",
        ]
        return "\n".join(lines)


@mcp.tool()
async def list_snapshots(project_id: int) -> str:
    """List all version snapshots for a project."""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_APP_BASE}/api/projects/{project_id}/snapshots/",
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        snaps = resp.json()
        if not snaps:
            return "No snapshots found."
        lines = ["Snapshots (newest first):"]
        for s in snaps:
            active = " ← ACTIVE" if s["is_active"] else ""
            lines.append(f"  v{s['version']}: {s['label']} ({s['created_at'][:10]}){active}")
        return "\n".join(lines)


@mcp.tool()
async def rollback_snapshot(project_id: int, version: int) -> str:
    """Rollback a project to a specific snapshot version.

    Use list_snapshots to see available versions.
    """
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_APP_BASE}/api/projects/{project_id}/snapshots/{version}/rollback",
            headers=_auth_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return f"Rolled back project {project_id} to v{version}."


@mcp.tool()
async def chat_with_agent(project_id: int, message: str) -> str:
    """Send a message to the AI agent for a project.

    The agent can suggest code changes, answer questions, and ask for clarification.
    Examples:
    - 'Add rate limiting to all tools'
    - 'Why was /users classified as a Resource?'
    - 'Regenerate with better error handling'
    """
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_APP_BASE}/api/projects/{project_id}/chat/send",
            json={"content": message},
            headers=_auth_headers(),
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        response = data.get("response", "")
        actions = data.get("actions_triggered", [])
        result = f"Agent: {response}"
        if actions:
            result += f"\n\nActions triggered: {', '.join(a['tool'] for a in actions)}"
        return result


@mcp.tool()
async def get_notifications(unread_only: bool = True) -> str:
    """Get dashboard notifications (agent questions, status updates, errors)."""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_APP_BASE}/api/notifications?unread_only={str(unread_only).lower()}",
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        notifs = resp.json()
        if not notifs:
            return "No notifications." if not unread_only else "No unread notifications."
        lines = []
        for n in notifs[:10]:
            lines.append(f"[{n['type'].upper()}] {n['title']}: {n['message']}")
        return "\n".join(lines)


@mcp.tool()
async def validate_generated_code(project_id: int) -> str:
    """Run validation and security audit on the generated MCP code."""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_APP_BASE}/api/projects/{project_id}/generate/validate",
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        result = resp.json()
        lines = [f"Valid: {result['valid']}"]
        if result.get("errors"):
            lines.append("Errors: " + "; ".join(result["errors"]))
        if result.get("warnings"):
            lines.append("Warnings: " + "; ".join(result["warnings"]))
        if result.get("security_issues"):
            lines.append("Security: " + "; ".join(result["security_issues"]))
        return "\n".join(lines)


# ── Resources ─────────────────────────────────────────────────────────────────

@mcp.resource("forge://projects")
async def projects_resource() -> str:
    """All projects in MCP Forge as a resource."""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{_APP_BASE}/api/projects/", headers=_auth_headers())
        return resp.text


@mcp.resource("forge://projects/{project_id}/analysis")
async def analysis_resource(project_id: str) -> str:
    """Analysis result for a specific project."""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_APP_BASE}/api/projects/{project_id}/analysis",
            headers=_auth_headers(),
        )
        return resp.text


# ── Helpers ───────────────────────────────────────────────────────────────────

def _auth_headers() -> dict:
    return {"X-MCP-Token": settings.mcp_auth_token}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        mcp.run(
            transport="sse",
            host="0.0.0.0",
            port=int(os.getenv("MCP_SERVER_PORT", str(settings.mcp_server_port))),
        )
    else:
        mcp.run()
