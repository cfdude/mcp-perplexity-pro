#!/usr/bin/env node

import { spawn } from 'child_process';
import { createServer } from 'http';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const projectRoot = dirname(__dirname);

// Default port for Claude Code
const DEFAULT_PORT = 8124;

function log(message: string) {
  console.error(`[claude-code-bridge] ${message}`);
}

/**
 * Check if a port is available
 */
async function isPortAvailable(port: number): Promise<boolean> {
  return new Promise(resolve => {
    const server = createServer();

    server.listen(port, () => {
      server.close(() => resolve(true));
    });

    server.on('error', () => resolve(false));
  });
}

/**
 * Simple health check without AbortSignal.timeout (Node 18 compatibility)
 */
async function checkServerHealth(port: number): Promise<boolean> {
  return new Promise(resolve => {
    const timeout = setTimeout(() => {
      resolve(false);
    }, 2000); // 2 second timeout

    fetch(`http://localhost:${port}/health`)
      .then(response => {
        clearTimeout(timeout);
        resolve(response.ok);
      })
      .catch(() => {
        clearTimeout(timeout);
        resolve(false);
      });
  });
}

/**
 * Start the HTTP server and return its process
 */
function startHttpServer(port: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const serverPath = join(projectRoot, 'dist', 'index.js');

    log(`Starting HTTP server on port ${port}...`);
    const serverProcess = spawn('node', [serverPath, `--port=${port}`], {
      stdio: 'inherit',
      env: { ...process.env },
      cwd: projectRoot,
    });

    serverProcess.on('error', error => {
      reject(new Error(`Failed to start HTTP server: ${error.message}`));
    });

    // Give the server a moment to start up
    setTimeout(() => {
      resolve();
    }, 1000);
  });
}

async function main() {
  try {
    // Check if server is already running
    if (await checkServerHealth(DEFAULT_PORT)) {
      log(`Found existing server on port ${DEFAULT_PORT}`);
      // For Claude Code, we need to act as a stdio bridge to the HTTP server
      const { StdioHttpBridge } = await import('./stdio-bridge.js');
      const bridge = new StdioHttpBridge();
      await bridge.start();
      return;
    }

    // Check if port is available
    if (!(await isPortAvailable(DEFAULT_PORT))) {
      throw new Error(`Port ${DEFAULT_PORT} is not available`);
    }

    // Start new HTTP server
    await startHttpServer(DEFAULT_PORT);

    // Wait for server to be healthy
    let attempts = 0;
    const maxAttempts = 10;
    while (attempts < maxAttempts) {
      if (await checkServerHealth(DEFAULT_PORT)) {
        log(`Server is healthy on port ${DEFAULT_PORT}`);
        break;
      }
      attempts++;
      await new Promise(resolve => setTimeout(resolve, 500));
    }

    if (attempts >= maxAttempts) {
      throw new Error('Server failed to become healthy after startup');
    }

    // Act as stdio bridge
    const { StdioHttpBridge } = await import('./stdio-bridge.js');
    const bridge = new StdioHttpBridge();
    await bridge.start();
  } catch (error) {
    log(`Error: ${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  }
}

main().catch(error => {
  log(`Bridge error: ${error}`);
  process.exit(1);
});
