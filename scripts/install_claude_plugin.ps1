# MCP Forge - Claude Desktop Plugin Installer (Windows)
# Usage: .\scripts\install_claude_plugin.ps1

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  MCP Forge - Claude Desktop Plugin Installer" -ForegroundColor Cyan
Write-Host "  ============================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Check Docker
Write-Host "[1/4] Checking Docker..." -ForegroundColor Yellow
$running = docker ps --format "{{.Names}}" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ERROR: Docker is not running." -ForegroundColor Red
    exit 1
}
if ($running -notmatch "mcp_forge_app") {
    Write-Host "  ERROR: mcp_forge_app is not running. Run 'docker compose up -d' first." -ForegroundColor Red
    exit 1
}
Write-Host "  Docker OK -- mcp_forge_app is running." -ForegroundColor Green

# Step 2: Get token
Write-Host "[2/4] Fetching auth token from container..." -ForegroundColor Yellow
$token = docker exec mcp_forge_app printenv MCP_AUTH_TOKEN
if (-not $token) {
    Write-Host "  ERROR: Could not read MCP_AUTH_TOKEN from container." -ForegroundColor Red
    exit 1
}
Write-Host "  Token fetched OK." -ForegroundColor Green

# Step 3: Write config
Write-Host "[3/4] Writing Claude Desktop config..." -ForegroundColor Yellow
$configDir = Join-Path $env:APPDATA "Claude"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null
$configPath = Join-Path $configDir "claude_desktop_config.json"

$json = [ordered]@{
    mcpServers = [ordered]@{
        "mcp-forge" = [ordered]@{
            url = "http://localhost:8001/sse"
            headers = [ordered]@{
                "X-MCP-Token" = $token
            }
        }
    }
}
$json | ConvertTo-Json -Depth 5 | Set-Content $configPath -Encoding UTF8

Write-Host "  Config written to: $configPath" -ForegroundColor Green

# Step 4: Done
Write-Host "[4/4] Done!" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor Cyan
Write-Host "  1. Fully QUIT Claude Desktop (system tray -> right-click -> Quit)"
Write-Host "  2. Reopen Claude Desktop"
Write-Host "  3. Go to Settings -> Developer -- look for mcp-forge with a green dot"
Write-Host "  4. Ask Claude: List all my MCP Forge projects"
Write-Host ""
