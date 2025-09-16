#!/usr/bin/env node

import { spawn, execSync } from 'child_process';
import { existsSync, statSync, readdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { discoverMcpPort, type PortDiscoveryResult } from './port-utils.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const projectRoot = dirname(__dirname);

function log(message: string) {
  console.error(`[mcp-perplexity-pro] ${message}`);
}

function checkBuildNeeded(): boolean {
  const distPath = join(projectRoot, 'dist');
  const srcPath = join(projectRoot, 'src');

  // If dist doesn't exist, build is needed
  if (!existsSync(distPath)) {
    log('dist/ directory not found, build required');
    return true;
  }

  // Check if any src file is newer than corresponding dist file
  try {
    const srcFiles = readdirSync(srcPath).filter(f => f.endsWith('.ts'));
    const distFiles = readdirSync(distPath).filter(f => f.endsWith('.js'));

    // If different number of files, build needed
    if (srcFiles.length === 0) {
      log('No TypeScript files found in src/');
      return true;
    }

    if (distFiles.length === 0) {
      log('No compiled JavaScript files found in dist/');
      return true;
    }

    // Check timestamps - find newest src file and oldest dist file
    let newestSrcTime = 0;
    let oldestDistTime = Infinity;

    for (const file of srcFiles) {
      const srcStat = statSync(join(srcPath, file));
      newestSrcTime = Math.max(newestSrcTime, srcStat.mtimeMs);
    }

    for (const file of distFiles) {
      const distStat = statSync(join(distPath, file));
      oldestDistTime = Math.min(oldestDistTime, distStat.mtimeMs);
    }

    if (newestSrcTime > oldestDistTime) {
      log('Source files newer than compiled files, build required');
      return true;
    }

    return false;
  } catch (error) {
    log(`Error checking build status: ${error}`);
    return true; // If we can't determine, err on side of building
  }
}

function runBuild(): void {
  log('Building MCP server...');
  try {
    execSync('npm run build', {
      cwd: projectRoot,
      stdio: 'inherit',
      timeout: 120000, // 2 minute timeout
    });
    log('Build completed successfully');
  } catch (error) {
    log(`Build failed: ${error}`);
    process.exit(1);
  }
}

function parseArgs(): { httpPort: number; debugMode: boolean; clientMode: 'stdio' | 'http' } {
  const args = process.argv.slice(2);
  let httpPort = 8124; // Default port for Claude Code
  let debugMode = false;
  let clientMode: 'stdio' | 'http' = 'stdio'; // Default to stdio mode

  for (const arg of args) {
    if (arg.startsWith('--http-port=')) {
      const portStr = arg.split('=')[1];
      const port = parseInt(portStr, 10);
      if (isNaN(port) || port <= 0 || port > 65535) {
        log(`Invalid port number: ${portStr}`);
        process.exit(1);
      }
      httpPort = port;
    } else if (arg.startsWith('--port=')) {
      // Alternative port syntax
      const portStr = arg.split('=')[1];
      const port = parseInt(portStr, 10);
      if (isNaN(port) || port <= 0 || port > 65535) {
        log(`Invalid port number: ${portStr}`);
        process.exit(1);
      }
      httpPort = port;
    } else if (arg === '--debug-mode') {
      debugMode = true;
    } else if (arg === '--http-client') {
      clientMode = 'http';
    } else if (arg === '--help' || arg === '-h') {
      console.log(`
mcp-perplexity-pro - Perplexity API MCP Server

Usage:
  mcp-perplexity-pro                    # Start HTTP server on port 8124 (for Claude Code)
  mcp-perplexity-pro --http-port=8125   # Start HTTP server on port 8125 (for Claude Desktop)
  mcp-perplexity-pro --debug-mode       # Enable debug logging to stdout

Environment Variables:
  PERPLEXITY_API_KEY    # Required: Your Perplexity API key
  DEFAULT_MODEL         # Optional: Default model (default: sonar-reasoning-pro)
  PROJECT_ROOT          # Optional: Project root directory
  STORAGE_PATH          # Optional: Storage subdirectory (default: .perplexity)
`);
      process.exit(0);
    }
  }

  return { httpPort, debugMode, clientMode };
}

function startServer(httpPort: number): void {
  const distPath = join(projectRoot, 'dist');

  // Always use HTTP mode - start the HTTP server
  log(`Starting HTTP server on port ${httpPort}...`);
  const serverPath = join(distPath, 'index.js');

  if (!existsSync(serverPath)) {
    log(`Server file not found: ${serverPath}`);
    process.exit(1);
  }

  const serverProcess = spawn('node', [serverPath, `--port=${httpPort}`], {
    stdio: 'inherit',
    env: { ...process.env },
    cwd: projectRoot,
  });

  serverProcess.on('error', error => {
    log(`Failed to start HTTP server: ${error}`);
    process.exit(1);
  });

  serverProcess.on('exit', code => {
    if (code !== 0) {
      log(`HTTP server exited with code ${code}`);
      process.exit(code || 1);
    }
  });

  // Handle graceful shutdown
  process.on('SIGINT', () => {
    log('Shutting down HTTP server...');
    serverProcess.kill('SIGINT');
  });

  process.on('SIGTERM', () => {
    log('Shutting down HTTP server...');
    serverProcess.kill('SIGTERM');
  });
}

async function main(): Promise<void> {
  const { httpPort: preferredPort, debugMode, clientMode } = parseArgs();

  // Set debug mode environment variable for child processes
  if (debugMode) {
    process.env.MCP_DEBUG_MODE = 'true';
  }

  // Discover the best port to use (check for existing servers or find available)
  let discovery: PortDiscoveryResult;
  try {
    discovery = await discoverMcpPort(preferredPort);

    if (discovery.isExistingServer) {
      if (clientMode === 'http') {
        // For HTTP client mode (Claude Code), output connection URL to stdout and exit
        console.log(`http://localhost:${discovery.port}`);
        process.exit(0);
      } else {
        // For stdio mode (Claude Desktop), log and exit as before
        log(`Found existing healthy MCP server on port ${discovery.port}`);
        log(`Clients can connect to: http://localhost:${discovery.port}`);
        log(`This instance will exit as the shared server is already running.`);
        process.exit(0);
      }
    } else {
      log(`No existing MCP server found. Starting new server on port ${discovery.port}`);
    }
  } catch (error) {
    log(`Port discovery failed: ${error}`);
    log(`Attempting to use preferred port ${preferredPort}`);
    discovery = { port: preferredPort, isExistingServer: false };
  }

  // Check if build is needed (skip if we're already in a build process)
  if (!process.env.npm_lifecycle_event && checkBuildNeeded()) {
    runBuild();
  }

  // Start the HTTP server on the discovered port
  startServer(discovery.port);
}

// Handle unhandled errors
process.on('uncaughtException', error => {
  log(`Uncaught exception: ${error}`);
  process.exit(1);
});

process.on('unhandledRejection', error => {
  log(`Unhandled rejection: ${error}`);
  process.exit(1);
});

main().catch(error => {
  log(`Launcher error: ${error}`);
  process.exit(1);
});
