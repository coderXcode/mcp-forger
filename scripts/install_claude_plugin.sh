#!/bin/bash
# =============================================================================
# MCP Forge — Claude Desktop Plugin Installer (macOS / Linux)
# Usage: bash scripts/install_claude_plugin.sh
# =============================================================================

set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo ""
echo -e "  ${CYAN}MCP Forge — Claude Desktop Plugin Installer${NC}"
echo -e "  ${CYAN}============================================${NC}"
echo ""

# --- Step 1: Check Docker is running ---
echo -e "${YELLOW}[1/4] Checking Docker...${NC}"
if ! docker ps --format "{{.Names}}" 2>/dev/null | grep -q "mcp_forge_app"; then
    echo -e "${RED}  ERROR: mcp_forge_app container is not running.${NC}"
    echo -e "${RED}  Run 'docker compose up -d' first, then re-run this script.${NC}"
    exit 1
fi
echo -e "${GREEN}  Docker OK — mcp_forge_app is running.${NC}"

# --- Step 2: Get auth token ---
echo -e "${YELLOW}[2/4] Fetching auth token from container...${NC}"
TOKEN=$(docker exec mcp_forge_app printenv MCP_AUTH_TOKEN)
if [ -z "$TOKEN" ]; then
    echo -e "${RED}  ERROR: Could not read MCP_AUTH_TOKEN from container.${NC}"
    exit 1
fi
echo -e "${GREEN}  Token fetched OK.${NC}"

# --- Step 3: Write the config file ---
echo -e "${YELLOW}[3/4] Writing Claude Desktop config...${NC}"

# macOS path
CONFIG_DIR="$HOME/Library/Application Support/Claude"

# Linux fallback (Claude Desktop on Linux uses XDG)
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/Claude"
fi

mkdir -p "$CONFIG_DIR"
CONFIG_PATH="$CONFIG_DIR/claude_desktop_config.json"

cat > "$CONFIG_PATH" <<EOF
{
  "mcpServers": {
    "mcp-forge": {
      "url": "http://localhost:8001/sse",
      "headers": {
        "X-MCP-Token": "$TOKEN"
      }
    }
  }
}
EOF

echo -e "${GREEN}  Config written to: $CONFIG_PATH${NC}"

# --- Step 4: Done ---
echo -e "${YELLOW}[4/4] Done!${NC}"
echo ""
echo -e "${CYAN}  Next steps:${NC}"
echo "  1. Fully QUIT Claude Desktop (menu bar → Quit)"
echo "  2. Reopen Claude Desktop"
echo "  3. Go to Settings → Developer — you should see 'mcp-forge' with a green dot"
echo "  4. Try asking: 'List all my MCP Forge projects'"
echo ""
