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

// Load configuration
const config = {
  api_key: process.env.PERPLEXITY_API_KEY || '',
  default_model: 'sonar-reasoning-pro',
  project_root: process.cwd(),
  storage_path: '.perplexity',
};

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