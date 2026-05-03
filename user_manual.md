# MCP Forge — User Manual

> Advanced configuration, Codex integration, local folder setup, troubleshooting, and architecture reference.
> For the main getting-started guide see [README.md](README.md) (or [PyPI](https://pypi.org/project/mcp-forger/)).

```bash
pip install mcp-forger   # install the forge CLI
```

---

## Table of Contents

1. [Generated Project: One-Command Claude Desktop Setup](#1-generated-project-one-command-claude-desktop-setup)
2. [Connect MCP Forge itself to Claude Desktop (Manual Config)](#2-connect-mcp-forge-itself-to-claude-desktop-manual-config)
3. [Connect to Claude Code](#3-connect-to-claude-code)
4. [Connect to Codex](#4-connect-to-codex)
5. [Using a Local Folder as Source](#5-using-a-local-folder-as-source)
6. [Local HuggingFace Model (No API Key)](#6-local-huggingface-model-no-api-key)
7. [Full Configuration Reference](#7-full-configuration-reference)
8. [Resetting the Database](#8-resetting-the-database)
9. [Available MCP Tools](#9-available-mcp-tools)
10. [Architecture](#10-architecture)

---

## 1. Generated Project: One-Command Claude Desktop Setup

When MCP Forge generates an MCP server for your project, it includes two setup scripts that automatically wire the generated server into Claude Desktop — no manual JSON editing required.

### What's stable, what's under testing

| Source type | Status |
|---|---|
| Local folder (`mnt/`) | ✅ Stable — recommended |
| OpenAPI / Swagger URL | 🧪 Under testing |
| GitHub repo | 🧪 Under testing |
| File upload | 🧪 Under testing |
| Live URL probing | 🧪 Under testing |
| Manual description | 🧪 Under testing |

| Output language | Status |
|---|---|
| Python FastMCP (`python_fastmcp`) | ✅ Stable — recommended |
| Node.js | 🚧 Under development & testing |
| Go | 🚧 Under development & testing |

### Files included in every generated project

> **Two plugins, not one.** After full setup you will see two separate entries in Claude Desktop → Settings → Developer:
> - **`mcp-forge`** — the workshop. Lets Claude create projects, generate code, run tests. Installed via `forge plugin install`.
> - **`your-project-name`** — the product. Lets Claude call your actual API directly. Installed via `bash configure_claude.sh`.
>
> They are independent. The generated plugin talks directly to your running app — it does **not** go through MCP Forge. Your original app must be running at `BASE_URL` for tool calls to return real data.

```
generated/<project-name>/
├── main.py                 ← the generated MCP server
├── requirements.txt        ← fastmcp, httpx, mcp
├── .env                    ← BASE_URL and API_TOKEN (pre-filled from your source)
├── configure_claude.sh     ← macOS / Linux one-command setup  (chmod 755)
├── configure_claude.ps1    ← Windows PowerShell equivalent
└── README.md               ← Quick Setup at the top
```

### Run the setup script

**macOS / Linux**
```bash
cd generated/<project-name>
bash configure_claude.sh
```

**Windows (PowerShell)**
```powershell
cd generated\<project-name>
.\configure_claude.ps1
```

### What the script does

1. **Detects your OS** — finds the correct `claude_desktop_config.json` path automatically
2. **Creates `.venv/`** — isolated Python virtual environment inside the project folder
3. **Installs dependencies** — runs `pip install -r requirements.txt` into the venv
4. **Reads `.env`** — picks up `BASE_URL` (or prompts you if it’s not set)
5. **Merges `mcpServers`** — adds your project entry without touching existing entries
6. **Prints restart instructions**

Then **fully quit and reopen Claude Desktop** (system tray → Quit — not just close the window). Your converted API appears as a new tool with a 🟢 green dot under **Settings → Developer**.

### Options

| Flag | Description |
|---|---|
| `--base-url <url>` | Override the target API base URL (e.g. `http://localhost:9000`) |

```bash
# Example: your API runs on port 9000
bash configure_claude.sh --base-url http://localhost:9000
```

### The `.env` file

Before running the script you can edit `.env` in the generated folder:

```env
BASE_URL=http://localhost:8000   # URL of the API being wrapped
API_TOKEN=                        # Bearer token if the API requires auth
```

`BASE_URL` is automatically pre-filled from the URL you provided when creating the project.

### What gets written to `claude_desktop_config.json`

```json
{
  "mcpServers": {
    "<project_name>": {
      "command": "/path/to/generated/<project-name>/.venv/bin/python",
      "args": ["/path/to/generated/<project-name>/main.py"],
      "env": {
        "BASE_URL": "http://localhost:8000",
        "MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

Existing entries (e.g. `mcp-forge` itself) are preserved — the script merges, not overwrites.

### Changing the base URL later

Edit `BASE_URL` in `.env` and re-run the script, or edit `claude_desktop_config.json` directly and restart Claude Desktop.

---

## 2. Connect MCP Forge itself to Claude Desktop (Manual Config)

> This section covers connecting **MCP Forge** (the forging tool itself) to Claude Desktop — not the generated servers. The install scripts (`install_claude_plugin.ps1` / `.sh`) or `forge plugin install` handle this automatically. Only use this section if you need to configure manually.

### Get your auth token

```bash
# macOS / Linux
grep -m1 '^MCP_AUTH_TOKEN=' .env | cut -d= -f2
# Windows (PowerShell)
(Get-Content .env | Where-Object { $_ -match '^MCP_AUTH_TOKEN=' }) -replace '^MCP_AUTH_TOKEN=',''
```

### Config file location

| OS | Path |
|---|---|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

### stdio config (recommended — works on all Claude Desktop versions)

```json
{
  "mcpServers": {
    "mcp-forge": {
      "command": "C:/path/to/mcp-forge/.venv/Scripts/python.exe",
      "args": ["mcp_server/server.py"],
      "cwd": "C:/path/to/mcp-forge",
      "env": {
        "APP_URL": "http://localhost:8000",
        "MCP_AUTH_TOKEN": "YOUR_TOKEN_HERE"
      }
    }
  }
}
```

> Replace `C:/path/to/mcp-forge` with the actual repo path on your machine.
> On macOS/Linux use `.venv/bin/python` instead of `.venv/Scripts/python.exe`.

### SSE config (newer Claude Desktop versions with Connectors UI)

```json
{
  "mcpServers": {
    "mcp-forge": {
      "url": "http://localhost:8001/sse",
      "headers": { "X-MCP-Token": "YOUR_TOKEN_HERE" }
    }
  }
}
```

Or via **Customize → Connectors → `+`** in Claude Desktop UI:
- Name: `mcp-forge`
- URL: `http://localhost:8001/sse`
- Header: `X-MCP-Token` / your token

### After configuring

1. Fully **QUIT** Claude Desktop (system tray / menu bar → Quit — not just close)
2. Reopen → **Settings → Developer** → look for **mcp-forge** with 🟢 green dot

### Changing the token later

Edit `MCP_AUTH_TOKEN=` in `.env` → `docker compose restart` → re-run install script or update the config file.

---

## 3. Connect to Claude Code

### Option A — Marketplace (recommended, no cloning needed)

In Claude Code terminal:

```
/plugin marketplace add coderXcode/mcp-forge
/plugin install mcp-forge@coderXcode-mcp-forge
```

Reload Claude Code — skills are available immediately.

### Option B — Auto-detected from repo root

Clone the repo and open it in Claude Code — `.mcp.json` at the root is picked up automatically.

Set your token before launching VS Code:

```powershell
# Windows
$env:FORGE_TOKEN = "your-token-here"

# macOS / Linux
export FORGE_TOKEN=your-token-here
```

### Skills

```
/forge:analyze <project_id>
/forge:generate <project_id>
/forge:chat <project_id> <message>
/forge:status
/forge:test <project_id>
/forge:rollback <project_id> <version>
```

---

## 4. Connect to Codex

```bash
# Install the forge CLI
pip install mcp-forger
pipx install mcp-forger
pip install git+https://github.com/coderXcode/mcp-forge.git   # directly from GitHub

# Add the plugin to Codex
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

## 5. Using a Local Folder as Source

> **This is the most reliable and recommended source type.** Other source types (OpenAPI URL, GitHub repo, file upload, URL probing) are under testing.

The `mnt/` folder next to `docker-compose.yml` is live-mounted into the container at `/mnt/`. Drop any project folder there — no Docker restart needed.

```
mcp-forge/
└── mnt/
    └── my-api/          ← copy your project folder here
        ├── main.py          (or app.py, server.py, etc.)
        └── requirements.txt
```

### Full workflow

**Step 1 — Copy your project into `mnt/`**
```bash
cp -r /path/to/my-api  mnt/my-api
```

**Step 2 — Create the project (pick one method)**

*Dashboard:*
- Open **http://localhost:8000** → **+ New Project**
- Source type = `Local Folder`
- Path = `/mnt/my-api`

*Claude Desktop:*
```
Create a new MCP Forge project called "my-api",
source type local_folder, path /mnt/my-api
```

*CLI:*
```bash
# Create via dashboard first, then trigger analysis
forge analyze 1
```

**Step 3 — Generate**

*Dashboard:* click **Generate** on the project page.

*Claude Desktop:*
```
Generate the MCP server for project 1 in Python FastMCP
```

*CLI:*
```bash
forge generate 1 --lang python_fastmcp
```

> **Language note:** Only **Python FastMCP** (`python_fastmcp`) is stable. Node.js, Go, and other targets are under development and testing.

**Step 4 — Run the setup script**
```bash
cd generated/my-api
bash configure_claude.sh
```

Then fully quit and reopen Claude Desktop.

> `mnt/` contents are gitignored — your code won't be committed.

---

## 6. Local HuggingFace Model (No API Key)

Requires NVIDIA GPU + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).

```env
LLM_PROVIDER=local
LOCAL_MODEL=Qwen/Qwen2.5-Coder-14B-Instruct   # any HuggingFace model ID
LOCAL_MODEL_DEVICE=auto
LOCAL_MODEL_LOAD_IN_4BIT=true
```

```bash
docker compose down && docker compose build && docker compose up -d
```

The model downloads on first use and is cached. Swap `LOCAL_MODEL` for any HuggingFace instruction model:

| Model | VRAM (4-bit) | Quality |
|---|---|---|
| `Qwen/Qwen2.5-Coder-7B-Instruct` | ~4 GB | Good |
| `Qwen/Qwen2.5-Coder-14B-Instruct` | ~8 GB | **Recommended** |
| `deepseek-ai/deepseek-coder-v2-lite-instruct` | ~8 GB | Very good |
| `Qwen/Qwen2.5-Coder-32B-Instruct` | ~18 GB | Best |
| `mistralai/Mistral-7B-Instruct-v0.3` | ~4 GB | General purpose |

> CPU-only: `LOCAL_MODEL_LOAD_IN_4BIT=false` + `LOCAL_MODEL_DEVICE=cpu` — slower but no GPU needed.

---

## 7. Full Configuration Reference

All settings live in `.env` — also editable live from the dashboard **Config** page.

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini` \| `anthropic` \| `openai` \| `local` |
| `GEMINI_API_KEY` | — | Google Gemini API key |
| `ANTHROPIC_API_KEY` | — | Anthropic Claude API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model name |
| `ANTHROPIC_MODEL` | `claude-3-5-sonnet-20241022` | Anthropic model |
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model |
| `LOCAL_MODEL` | `Qwen/Qwen2.5-Coder-14B-Instruct` | HuggingFace model ID |
| `LOCAL_MODEL_DEVICE` | `auto` | `auto` \| `cuda` \| `cpu` |
| `LOCAL_MODEL_LOAD_IN_4BIT` | `true` | 4-bit NF4 quantization (NVIDIA GPU required) |
| `GITHUB_TOKEN` | — | PAT for private GitHub repo ingestion |
| `DB_URL` | `sqlite:///./data/mcp_forge.db` | SQLite or PostgreSQL URL |
| `MCP_AUTH_TOKEN` | `change-me-mcp-secret` | Auth token — **change this** |
| `MCP_SERVER_PORT` | `8001` | MCP SSE server port |
| `OUTPUT_DIR` | `./generated` | Where generated files are written |
| `ENABLE_GIT_SNAPSHOTS` | `false` | Auto-commit snapshots to git |
| `ENABLE_LIVE_PROBING` | `true` | Allow live URL probing during analysis |
| `ENABLE_SECURITY_AUDIT` | `true` | Scan generated code for security issues |
| `SECRET_KEY` | auto | FastAPI session secret |
| `DEBUG` | `false` | Verbose logs + uvicorn reload |

---

## 8. Resetting the Database

```bash
# Clear all rows (schema preserved)
echo y | docker exec -i mcp_forge_app python clear_db.py

# Full reset including volumes
docker compose down -v && docker compose up -d
```

---

## 9. Available MCP Tools

These are the tools exposed to Claude Desktop / Claude Code / Codex:

| Tool | What it does |
|---|---|
| `create_project` | Create a project and auto-start analysis |
| `list_projects` | List all projects with status |
| `analyze_source` | Trigger / re-trigger source analysis |
| `generate_mcp` | Generate the MCP server code |
| `get_generated_code` | Read generated files |
| `get_project_status` | Poll status (built-in long-poll — waits for change) |
| `run_tests` | Run AI-generated tests |
| `get_test_results` | Latest pass/fail counts |
| `list_snapshots` | All versioned snapshots |
| `rollback_snapshot` | Restore a previous snapshot |
| `chat_with_agent` | Talk to the AI forge agent |
| `get_notifications` | Bell notifications (questions, errors) |
| `get_clarifications` | List pending clarification questions |
| `answer_clarification` | Answer a clarification question |
| `validate_generated_code` | Security + structure audit |

---

## 10. Architecture

```
Claude Desktop / Claude Code / Codex
        │
        │  stdio  (Claude Desktop — via install script)
        │  SSE http://localhost:8001/sse  (Claude Code / Codex / Connectors UI)
        ▼
 mcp_server/server.py     ←  FastMCP  ·  15 tools
        │
        │  httpx REST  (X-MCP-Token header)
        ▼
 http://localhost:8000     ←  MCP Forge  ·  FastAPI
        │
        ├── SQLite  (projects · snapshots · chat · tests · notifications)
        ├── LLM     (Gemini / Anthropic / OpenAI / Local HuggingFace NF4)
        └── ./generated/   ←  output MCP server files

forge CLI  ──────────────────────────────────────────────────►  http://localhost:8000
(pip install mcp-forger)                                         REST API  (X-MCP-Token)
```
