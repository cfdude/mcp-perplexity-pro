#!/usr/bin/env node

import { createHTTPStreamingServer } from './http-streaming-server.js';
import { configSchema } from './types.js';

// Default port
let PORT = 8125;

// Parse command-line arguments for --port=XXXX
for (let i = 2; i < process.argv.length; i++) {
  const arg = process.argv[i];
  if (arg.startsWith('--port=')) {
    const value = parseInt(arg.split('=')[1], 10);
    if (!isNaN(value)) {
      PORT = value;
    } else {
      console.error('Invalid value for --port');
      process.exit(1);
    }
  }
}

// Load configuration - try multiple sources for API key
const apiKey = process.env.PERPLEXITY_API_KEY || 
              process.env.API_KEY || 
              process.env.PERPLEXITY_API_TOKEN ||
              '';

const config = {
  api_key: apiKey,
  default_model: 'sonar-reasoning-pro',
  project_root: process.cwd(),
  storage_path: '.perplexity',
};

// Debug API key
console.log(`API key loaded: ${config.api_key ? 'YES (' + config.api_key.substring(0, 10) + '...)' : 'NO'}`);

// Validate configuration
const validatedConfig = configSchema.parse(config);

const app = createHTTPStreamingServer(validatedConfig);

app.listen(PORT, () => {
  console.log(`MCP Perplexity HTTP Streaming Server listening on port ${PORT}`);
  console.log(`Claude Code can connect using: claude mcp add --transport http perplexity-http http://localhost:${PORT}`);
});

process.on('SIGINT', () => {
  console.log('Shutting down HTTP streaming server...');
  process.exit(0);
});