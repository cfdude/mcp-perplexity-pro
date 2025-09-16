import { createServer } from 'http';

// Port range for MCP server discovery (Claude Code uses 8124, Claude Desktop uses 8125)
const MCP_PORT_RANGE = { start: 8124, end: 8133 };

export interface PortDiscoveryResult {
  port: number;
  isExistingServer: boolean;
  healthStatus?: 'healthy' | 'unhealthy';
}

/**
 * Checks if a port is available for binding
 */
export async function isPortAvailable(port: number): Promise<boolean> {
  return new Promise(resolve => {
    const server = createServer();

    server.listen(port, () => {
      server.close(() => resolve(true));
    });

    server.on('error', () => resolve(false));
  });
}

/**
 * Checks if an MCP server is running on the specified port
 */
export async function checkMcpServerHealth(
  port: number
): Promise<'healthy' | 'unhealthy' | 'not-running'> {
  try {
    const response = await fetch(`http://localhost:${port}/health`, {
      method: 'GET',
      signal: AbortSignal.timeout(2000), // 2 second timeout
    });

    if (response.ok) {
      const health = await response.json();
      return health.status === 'healthy' ? 'healthy' : 'unhealthy';
    } else {
      return 'unhealthy';
    }
  } catch (error) {
    // Port might be occupied by non-MCP service or not running
    const available = await isPortAvailable(port);
    return available ? 'not-running' : 'unhealthy';
  }
}

/**
 * Discovers the best port to use for the MCP server
 * Strategy:
 * 1. Check if there's already a healthy MCP server running in the port range
 * 2. If yes, return that port (shared server model)
 * 3. If no, find the first available port in the range
 * 4. If none available in range, throw an error
 */
export async function discoverMcpPort(preferredPort?: number): Promise<PortDiscoveryResult> {
  const debugMode = process.env.MCP_DEBUG_MODE === 'true';
  const debugLog = debugMode ? console.log : console.error;

  debugLog(`Discovering MCP server port (preferred: ${preferredPort || 'none'})`);

  // First, check if preferred port has a healthy MCP server
  if (preferredPort) {
    const health = await checkMcpServerHealth(preferredPort);
    if (health === 'healthy') {
      debugLog(`Found healthy MCP server on preferred port ${preferredPort}`);
      return {
        port: preferredPort,
        isExistingServer: true,
        healthStatus: 'healthy',
      };
    }
  }

  // Scan the entire port range for existing healthy MCP servers
  for (let port = MCP_PORT_RANGE.start; port <= MCP_PORT_RANGE.end; port++) {
    const health = await checkMcpServerHealth(port);
    if (health === 'healthy') {
      debugLog(`Found healthy MCP server on port ${port}`);
      return {
        port,
        isExistingServer: true,
        healthStatus: 'healthy',
      };
    }
  }

  // No existing healthy server found, find an available port
  // Start with preferred port if specified and available
  if (preferredPort && (await isPortAvailable(preferredPort))) {
    debugLog(`Using preferred port ${preferredPort} (no existing server found)`);
    return {
      port: preferredPort,
      isExistingServer: false,
    };
  }

  // Find first available port in range
  for (let port = MCP_PORT_RANGE.start; port <= MCP_PORT_RANGE.end; port++) {
    if (await isPortAvailable(port)) {
      debugLog(`Using available port ${port}`);
      return {
        port,
        isExistingServer: false,
      };
    }
  }

  // No ports available in the range
  throw new Error(
    `No available ports in MCP range ${MCP_PORT_RANGE.start}-${MCP_PORT_RANGE.end}. ` +
      'Please free up a port or use a different range.'
  );
}

/**
 * Lists all ports in the MCP range and their status
 */
export async function scanMcpPortRange(): Promise<
  Array<{
    port: number;
    available: boolean;
    mcpHealth: 'healthy' | 'unhealthy' | 'not-running';
  }>
> {
  const results = [];

  for (let port = MCP_PORT_RANGE.start; port <= MCP_PORT_RANGE.end; port++) {
    const available = await isPortAvailable(port);
    const mcpHealth = available ? 'not-running' : await checkMcpServerHealth(port);

    results.push({
      port,
      available,
      mcpHealth,
    });
  }

  return results;
}
