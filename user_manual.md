# MCP Forge — User Manual

> Connect MCP Forge to Claude Desktop, Claude Code, or Codex and let AI drive your entire API-to-MCP conversion workflow from natural language.

---

## Requirements

| Tool | Version |
|---|---|
| Docker + Docker Compose | v24+ |
| NVIDIA GPU *(optional)* | Only needed for local LLM inference |

No Python installation required unless you want the `forge` CLI.

---

## Part 1 — Run MCP Forge

### Step 1 — Get the code

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO
```

### Step 2 — Configure

```bash
cp .env.example .env
```

Open `.env` and fill in at least one LLM provider key:

```env
# Pick ONE provider — or use "local" for no API key (requires GPU)
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-key-here

# Change this to something secret — used to authenticate Claude/Codex
MCP_AUTH_TOKEN=change-me-to-something-secret
```

> **No GPU?** Use `LLM_PROVIDER=gemini` (free tier available at [aistudio.google.com](https://aistudio.google.com)) or `anthropic` / `openai`.

### Step 3 — Start

```bash
docker compose up -d
```

| Service | URL |
|---|---|
| 🌐 Dashboard | http://localhost:8000 |
| 🔌 MCP SSE endpoint | http://localhost:8001/sse |

### Step 4 — Verify

```bash
# Should return a JSON list of projects (empty at first)
curl http://localhost:8000/api/projects/

# Should return: event: endpoint  (confirms MCP server is running)
curl http://localhost:8001/sse
```

---

## Part 2 — Connect to Claude Desktop

### Get your auth token

```powershell
# PowerShell (Windows)
docker exec mcp_forge_app printenv MCP_AUTH_TOKEN

# Terminal (macOS / Linux)
docker exec mcp_forge_app printenv MCP_AUTH_TOKEN
```

> To change the token: edit `MCP_AUTH_TOKEN=` in your `.env` file, then run `docker compose restart`.

---

### Option A — Edit the config file (always works)

**Config file location:**

| OS | Path |
|---|---|
| Windows | `C:\Users\<YourName>\AppData\Roaming\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |

> Create the `Claude` folder if it doesn't exist.

**Paste this into the file** (replace `YOUR_TOKEN_HERE`):

```json
{
  "mcpServers": {
    "mcp-forge": {
      "url": "http://localhost:8001/sse",
      "headers": {
        "X-MCP-Token": "YOUR_TOKEN_HERE"
      }
    }
  }
}
```

**Windows PowerShell one-liner** — auto-pulls the token from Docker and writes the file:

```powershell
$dir = "$env:APPDATA\Claude"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$token = docker exec mcp_forge_app printenv MCP_AUTH_TOKEN
@"
{
  "mcpServers": {
    "mcp-forge": {
      "url": "http://localhost:8001/sse",
      "headers": { "X-MCP-Token": "$token" }
    }
  }
}
"@ | Set-Content "$dir\claude_desktop_config.json" -Encoding UTF8
Write-Host "Done: $dir\claude_desktop_config.json"
```

**Fully quit and reopen Claude Desktop** (system tray → Quit, not just close the window).

---

### Option B — Via Claude Desktop UI (Connectors)

Works on newer Claude Desktop versions with the **Customize** screen:

1. Open Claude Desktop → click **Customize** in the left sidebar
2. Click **Connectors** → **`+`** next to "Personal plugins"
3. Fill in:
   - **Name:** `mcp-forge`
   - **URL:** `http://localhost:8001/sse`
   - **Header name:** `X-MCP-Token`
   - **Header value:** *(your token)*
4. Save, then fully restart Claude Desktop

> ⚠️ If there is no URL field (only OAuth connectors), use **Option A** instead.

---

### Verify the connection

1. Open Claude Desktop → **Settings** (gear) → **Developer**
2. You should see **mcp-forge** with a 🟢 green dot
3. Test it — ask Claude: *"List all my MCP Forge projects"*

---

## Part 3 — Connect to Claude Code (VS Code)

The repo already contains a `.mcp.json` at the root — Claude Code picks it up automatically.

Set your token as an environment variable in your shell:

```powershell
# Windows PowerShell
$env:FORGE_TOKEN = "your-token-here"

# macOS / Linux
export FORGE_TOKEN=your-token-here
```

Then use skills directly in Claude Code:

```
/forge:analyze <project_id>
/forge:generate <project_id>
/forge:chat <project_id> <message>
/forge:status
/forge:test <project_id>
/forge:rollback <project_id> <version>
```

---

## Part 4 — Connect to Codex

```bash
# Install the forge CLI
pip install mcp-forge
# or: pipx install mcp-forge
# or: pip install git+https://github.com/YOUR_USERNAME/YOUR_REPO.git

# Add the plugin
codex marketplace add mcp-forge/mcp-forge
```

Skills in Codex:

```
$forge discover          # list all projects
$forge analyze 1         # trigger analysis
$forge generate 1        # generate MCP server
$forge chat 1 "message"  # chat with AI agent
```

---

## Part 5 — What You Can Do

### Ask Claude anything like:

```
Create a new MCP Forge project called "petstore" from
https://petstore3.swagger.io/api/v3/openapi.json
```
```
Analyze project 1 and tell me what endpoints were found
```
```
Generate the MCP server for project 1 in Python FastMCP
```
```
Show me the generated code for project 1
```
```
Run tests for project 1
```
```
Do I have any unread notifications in MCP Forge?
```
```
Chat with the forge agent for project 1:
"Review all endpoints and ask me anything unclear before generating"
```

### All available tools

| Tool | What it does |
|---|---|
| `create_project` | Create project + auto-start analysis |
| `list_projects` | All projects with status |
| `analyze_source` | Trigger / re-trigger analysis |
| `generate_mcp` | Generate MCP server code |
| `get_generated_code` | Read generated files |
| `run_tests` | Run AI-generated tests |
| `get_test_results` | Latest pass/fail counts |
| `list_snapshots` | All versioned snapshots |
| `rollback_snapshot` | Restore a snapshot |
| `chat_with_agent` | Talk to the AI forge agent |
| `get_notifications` | Bell notifications (questions, errors) |
| `validate_generated_code` | Security + structure audit |

---

## Troubleshooting

### mcp-forge not showing in Claude Desktop / red dot

- **Fully quit** Claude Desktop (system tray → Quit, not just close)
- Verify the `Claude` config folder exists (see paths above)
- Validate your JSON at [jsonlint.com](https://jsonlint.com) — a missing comma breaks it
- Make sure Docker is still running: `docker ps`

### "Connection refused" on port 8001

```bash
docker ps                             # confirm mcp_forge_mcp is Up
docker logs mcp_forge_mcp --tail 30   # check for startup errors
docker compose up -d                  # restart if needed
```

### Wrong or expired auth token

```bash
docker exec mcp_forge_app printenv MCP_AUTH_TOKEN
# Copy this value and update your claude_desktop_config.json
```

### `url:` field not supported in your Claude Desktop version

Use **stdio mode** — replace the config file contents with:

```json
{
  "mcpServers": {
    "mcp-forge": {
      "command": "python",
      "args": ["mcp_server/server.py"],
      "cwd": "C:/path/to/YOUR_REPO",
      "env": {
        "PYTHONPATH": "C:/path/to/YOUR_REPO",
        "APP_URL": "http://localhost:8000",
        "MCP_AUTH_TOKEN": "YOUR_TOKEN_HERE",
        "MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

> Requires Python 3.12+ and: `pip install fastmcp httpx sqlmodel pydantic-settings`

---

## Architecture (for the curious)

```
Claude Desktop / Claude Code / Codex
        │
        │  stdio  OR  SSE (http://localhost:8001/sse)
        ▼
 mcp_server/server.py      ←  FastMCP  ·  11 tools  ·  2 resources
        │
        │  httpx REST  (X-MCP-Token header)
        ▼
 http://localhost:8000      ←  MCP Forge  ·  FastAPI
        │
        ├── SQLite (projects, snapshots, chat, tests, notifications)
        ├── LLM  (Gemini / Anthropic / OpenAI / Local Qwen NF4)
        └── ./generated/   ←  output MCP server files
```
