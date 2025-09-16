#!/usr/bin/env node
/**
 * Stdio-HTTP Bridge for Claude Desktop
 *
 * This bridge provides stdio compatibility for Claude Desktop while using
 * our modern HTTP transport internally. Best of both worlds:
 * - Claude Desktop gets the stdio interface it expects
 * - We use HTTP transport internally (future-proof, not deprecated)
 * - Single codebase supports both transports
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { spawn } from 'child_process';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const projectRoot = dirname(__dirname);

export class StdioHttpBridge {
  private httpPort = 8125;
  private httpServerProcess: any = null;
  private server: Server;

  constructor() {
    // Create MCP server with stdio transport
    this.server = new Server(
      {
        name: 'mcp-perplexity-pro',
        version: '1.0.0',
      },
      {
        capabilities: {
          tools: {},
          progress: true,
        },
      }
    );

    this.setupMcpHandlers();
  }

  async start() {
    // Start HTTP server in background
    await this.startHttpServer();

    // Wait for HTTP server to be ready
    await this.waitForHttpServer();

    // Connect MCP server with stdio transport
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
  }

  private async startHttpServer(): Promise<void> {
    const launcherPath = join(projectRoot, 'dist', 'launcher.js');

    this.httpServerProcess = spawn('node', [launcherPath, `--http-port=${this.httpPort}`], {
      stdio: ['ignore', 'pipe', 'pipe'], // Capture output to prevent stdio pollution
      env: { ...process.env },
      cwd: projectRoot,
    });

    this.httpServerProcess.on('error', (error: any) => {
      console.error(`HTTP server failed: ${error}`);
      process.exit(1);
    });

    this.httpServerProcess.on('exit', (code: number) => {
      if (code !== 0) {
        console.error(`HTTP server exited with code ${code}`);
        process.exit(code || 1);
      }
    });

    // Graceful shutdown
    process.on('SIGINT', () => {
      if (this.httpServerProcess) {
        this.httpServerProcess.kill('SIGINT');
      }
      process.exit(0);
    });

    process.on('SIGTERM', () => {
      if (this.httpServerProcess) {
        this.httpServerProcess.kill('SIGTERM');
      }
      process.exit(0);
    });
  }

  private async waitForHttpServer(): Promise<void> {
    const maxAttempts = 30; // 15 seconds
    let attempts = 0;

    while (attempts < maxAttempts) {
      try {
        const response = await fetch(`http://localhost:${this.httpPort}/health`);
        if (response.ok) {
          const health = await response.json();
          if (health.status === 'healthy') {
            return; // Server is ready
          }
        }
      } catch (error) {
        // Server not ready yet
      }

      attempts++;
      await new Promise(resolve => setTimeout(resolve, 500));
    }

    throw new Error('HTTP server failed to start within 15 seconds');
  }

  private setupMcpHandlers(): void {
    // List tools - proxy to HTTP server
    this.server.setRequestHandler(ListToolsRequestSchema, async () => {
      try {
        const response = await fetch(`http://localhost:${this.httpPort}/api/tools`, {
          method: 'GET',
          headers: { 'Content-Type': 'application/json' },
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const tools = await response.json();
        return { tools };
      } catch (error) {
        throw new Error(`Failed to list tools: ${error}`);
      }
    });

    // Call tool - proxy to HTTP server
    this.server.setRequestHandler(CallToolRequestSchema, async request => {
      const { name, arguments: args } = request.params;

      try {
        const response = await fetch(`http://localhost:${this.httpPort}/api/tools/${name}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(args),
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
        };
      } catch (error) {
        return {
          content: [{ type: 'text', text: `Error: ${error}` }],
          isError: true,
        };
      }
    });
  }
}

// Start the bridge
async function main() {
  try {
    const bridge = new StdioHttpBridge();
    await bridge.start();
  } catch (error) {
    console.error(`Bridge startup failed: ${error}`);
    process.exit(1);
  }
}

main().catch(error => {
  console.error(`Bridge error: ${error}`);
  process.exit(1);
});
