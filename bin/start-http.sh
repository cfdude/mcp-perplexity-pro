#!/bin/bash
# MCP Perplexity Pro - HTTP Server Startup Script
# This script starts the MCP server in HTTP streaming mode

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PORT="${MCP_PERPLEXITY_PORT:-8102}"
LOG_DIR="/Users/robsherman/Library/Logs/mcp-perplexity-pro"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Change to project directory
cd "$PROJECT_DIR"

# Check if dist exists and is up to date
if [ ! -d "dist" ] || [ "$(find src -name '*.ts' -newer dist/index.js 2>/dev/null | head -1)" ]; then
    echo "[mcp-perplexity-pro] Building project..."
    npm run build
fi

# Check if PERPLEXITY_API_KEY is set
if [ -z "$PERPLEXITY_API_KEY" ]; then
    echo "[mcp-perplexity-pro] WARNING: PERPLEXITY_API_KEY is not set"
    echo "[mcp-perplexity-pro] Set it in the launchd plist or export it before running"
fi

# Start the HTTP streaming server
echo "[mcp-perplexity-pro] Starting HTTP server on port $PORT..."
exec node "$PROJECT_DIR/dist/index.js" --port="$PORT"
