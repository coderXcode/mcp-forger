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
from typing import Literal, Optional

# Add project root to path when run standalone
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastmcp import FastMCP, Context

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
    source_url: str = "",
    source_type: str = "openapi",
    target_language: str = "python_fastmcp",
    description: str = "",
    ctx: Context = None,
) -> str:
    """Create a new MCP conversion project.

    source_type options (ask user to pick one):
      - openapi       → OpenAPI / Swagger spec URL
      - github        → GitHub repository URL
      - url           → Public URL / running app
      - local_folder  → Local folder placed inside mcp-forge/mnt/ directory
      - upload        → Upload a zip or file
      - manual        → Describe the API manually (no source)

    For local_folder: the user must copy their project folder into the mnt/ directory
    next to docker-compose.yml, e.g. mcp-forge/mnt/myproject, then source_url="/mnt/myproject".

    target_language options:
      - python_fastmcp  → Python (FastMCP)
      - nodejs          → Node.js
      - go              → Go
      - generic         → Generic

    Always ask the user which source_type and target_language they want before calling.
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
        pid = data["id"]
        return (
            f"Project '{name}' created (id={pid}). Analysis has started automatically.\n"
            f"Call get_project_status({pid}) to track progress — keep calling it until status is 'ready'."
        )


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
async def analyze_source(project_id: int, source_url: str | None = None, ctx: Context = None) -> str:
    """Trigger source code / API analysis for a project and wait for it to complete.

    Optionally provide a new source_url to override the project's current source.
    Returns a summary of what was found once analysis finishes.
    """
    import httpx, asyncio
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
        return (
            f"Analysis started for project {project_id}.\n"
            f"Call get_project_status({project_id}) to track progress — keep calling it until status is 'ready'."
        )


@mcp.tool()
async def generate_mcp(
    project_id: int,
    target_language: str = "python_fastmcp",
    label: str = "",
    description: str = "",
    ctx: Context = None,
) -> str:
    """Generate MCP server code for a project and wait for it to complete.

    target_language: python_fastmcp | nodejs | go | generic
    Requires analysis to have been run first.
    Returns confirmation and a preview of generated files when done.
    """
    import httpx, asyncio
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_APP_BASE}/api/projects/{project_id}/generate/",
            json={"target_language": target_language, "label": label, "description": description},
            headers=_auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return (
            f"Generation started for project {project_id} (target: {target_language}).\n"
            f"Call get_project_status({project_id}) to track progress — keep calling it until status is 'ready'."
        )


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
async def run_tests(project_id: int, regenerate_tests: bool = False, ctx: Context = None) -> str:
    """Trigger test run for the generated MCP server. Returns immediately.

    regenerate_tests: if True, the agent will generate new test cases before running.
    After calling this, use get_project_status(project_id) to track progress.
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
        return (
            f"Test run started for project {project_id}.\n"
            f"Call get_project_status({project_id}) to track progress — keep calling until tests complete."
        )


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
async def get_project_status(project_id: int, wait_for_change: bool = True) -> str:
    """Check the current status of a project, optionally waiting until the status changes.

    When wait_for_change=True (default), this call blocks server-side for up to 30 seconds
    until the status changes from its current value, then returns. This means you only need
    to call this ONCE after starting an operation — it will return automatically when the
    next phase begins. Only call again if the returned status is still in-progress.

    IMPORTANT: Call this ONCE after each operation. Only call again if status is still
    pending/analyzing/generating/testing. Do NOT loop more than 3 times total — if still
    in progress after 3 calls, tell the user to check back and wait.

    Status values:
      pending    → just created, waiting to start
      analyzing  → reading and parsing the source code/API
      clarifying → agent has questions — call get_clarifications(project_id)
      generating → LLM is writing the MCP server code
      testing    → running the test suite
      ready      → all done! generation complete and tests passed
      error      → something went wrong — check the dashboard
    """
    import asyncio
    import httpx

    IN_PROGRESS = {"pending", "analyzing", "generating", "testing"}

    async with httpx.AsyncClient() as client:
        r = await client.get(f"{_APP_BASE}/api/projects/{project_id}", headers=_auth_headers())
        r.raise_for_status()
        p = r.json()
        initial_status = p.get("status", "unknown")

        # Long-poll: wait up to 30s for status to change if still in-progress
        if wait_for_change and initial_status in IN_PROGRESS:
            deadline = 30
            interval = 3
            elapsed = 0
            while elapsed < deadline:
                await asyncio.sleep(interval)
                elapsed += interval
                r2 = await client.get(f"{_APP_BASE}/api/projects/{project_id}", headers=_auth_headers())
                if r2.status_code == 200:
                    p = r2.json()
                    new_status = p.get("status", "unknown")
                    if new_status != initial_status:
                        break  # status changed — return immediately

        status = p.get("status", "unknown")
        status_messages = {
            "pending":    "⏳ Pending — queued, will start shortly.",
            "analyzing":  "🔍 Analyzing — reading and parsing your source code/API spec...",
            "clarifying": "❓ Clarifying — the agent has questions! Call get_clarifications({id}) to see and answer them.",
            "generating": "⚙️  Generating — LLM is writing the MCP server code...",
            "testing":    "🧪 Testing — running the test suite...",
            "ready":      "✅ Ready — operation complete!",
            "error":      "❌ Error — something went wrong. Check the dashboard for details.",
        }
        msg = status_messages.get(status, f"Status: {status}").replace("{id}", str(project_id))

        next_step = ""
        if status in IN_PROGRESS:
            next_step = " Still in progress — call get_project_status once more to continue waiting."
        elif status == "ready":
            fr = await client.get(f"{_APP_BASE}/api/projects/{project_id}/generate/files", headers=_auth_headers())
            if fr.status_code == 200 and fr.json().get("files"):
                files = list(fr.json()["files"].keys())
                next_step = f"\nGenerated files: {', '.join(files)}\nYou can now run_tests({project_id}) or get_generated_code({project_id})."
            else:
                next_step = f"\nReady to generate! Call generate_mcp({project_id}) to create the MCP server code."
        elif status == "clarifying":
            next_step = f" Call get_clarifications({project_id}) to answer the agent's questions."

        return f"Project {project_id} ({p.get('name', '')}): {msg}{next_step}"
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
async def get_clarifications(project_id: int, unanswered_only: bool = True) -> str:
    """Get pending clarification questions the agent has raised for a project.

    The agent emits clarification questions when it encounters ambiguous design
    decisions. Answer them with answer_clarification so they are used in generation.
    """
    import httpx
    async with httpx.AsyncClient() as client:
        params = {"is_resolved": "false"} if unanswered_only else {}
        resp = await client.get(
            f"{_APP_BASE}/api/projects/{project_id}/chat/clarifications",
            params=params,
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        items = resp.json()
        if not items:
            msg = "No pending clarifications." if unanswered_only else "No clarifications found."
            return msg
        lines = [f"{'Pending' if unanswered_only else 'All'} clarifications for project {project_id}:"]
        for c in items:
            status = "✅ answered" if c.get("is_resolved") else "❓ pending"
            lines.append(f"  [{c['id']}] {status} — {c['question']}")
            if c.get("answer"):
                lines.append(f"       Answer: {c['answer']}")
        return "\n".join(lines)


@mcp.tool()
async def answer_clarification(project_id: int, clarification_id: int, answer: str) -> str:
    """Answer a pending clarification question raised by the agent.

    Use get_clarifications to find clarification IDs.
    The answer will be injected into the next code generation pass.
    """
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_APP_BASE}/api/projects/{project_id}/chat/clarifications/{clarification_id}/answer",
            json={"answer": answer},
            headers=_auth_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return f"Clarification #{clarification_id} answered. It will be applied in the next generation."


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
