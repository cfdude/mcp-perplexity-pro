#!/bin/bash

# Docker entrypoint for stdio transport
# This script starts the MCP server with stdio transport for Docker deployment

set -e

# Check if API key is provided
if [ -z "$PERPLEXITY_API_KEY" ]; then
    echo "Error: PERPLEXITY_API_KEY environment variable is required" >&2
    exit 1
fi

# Set default values for environment variables if not provided
export PROJECT_ROOT="${PROJECT_ROOT:-/app/data}"
export STORAGE_PATH="${STORAGE_PATH:-.perplexity}"
export DEFAULT_MODEL="${DEFAULT_MODEL:-sonar-reasoning-pro}"

# Create data directory if it doesn't exist
mkdir -p "$PROJECT_ROOT"

# Change to the data directory so .perplexity files are stored there
cd "$PROJECT_ROOT"

# Start the stdio server
exec node /app/dist/stdio-server.js