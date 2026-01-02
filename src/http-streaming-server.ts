import express from 'express';
import cors from 'cors';
import { randomUUID } from 'crypto';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { z } from 'zod';
import { configSchema } from './types.js';
import { handleAskPerplexity, handleResearchPerplexity } from './tools/query.js';
import {
  handleChatPerplexity,
  handleListChats,
  handleReadChat,
  handleStorageStats,
} from './tools/chat.js';
import { handleAsyncPerplexity, handleCheckAsync, handleListAsyncJobs } from './tools/async.js';
import { handleListProjects, handleDeleteProject } from './tools/projects.js';
import { getModelSummary } from './models.js';

// Tool definitions - shared across all server instances
const TOOL_DEFINITIONS = [
  {
    name: 'ask_perplexity',
    description: 'Query Perplexity with automatic model selection based on complexity.',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'Your question or prompt' },
        project_name: {
          type: 'string',
          description:
            'Project name for organizing conversations (auto-detected if not provided)',
        },
        model: {
          type: 'string',
          enum: ['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'],
          description: 'Override default model',
        },
        temperature: {
          type: 'number',
          minimum: 0,
          maximum: 1,
          description: '0.0-1.0, default 0.2',
        },
        max_tokens: { type: 'number', minimum: 1, description: 'Maximum response length' },
        search_domain_filter: {
          type: 'array',
          items: { type: 'string' },
          description: 'Limit search to specific domains',
        },
        return_images: { type: 'boolean', description: 'Include images in response' },
        return_related_questions: {
          type: 'boolean',
          description: 'Include related questions',
        },
        save_report: {
          type: 'boolean',
          description: 'Save response as a report to project directory',
        },
      },
      required: ['query'],
    },
  },
  {
    name: 'research_perplexity',
    description: 'Conduct comprehensive research using sonar-deep-research model.',
    inputSchema: {
      type: 'object',
      properties: {
        topic: { type: 'string', description: 'Research topic or question' },
        project_name: {
          type: 'string',
          description:
            'Project name for organizing research reports (auto-detected if not provided)',
        },
        save_report: { type: 'boolean', description: 'Save report to project directory' },
        model: {
          type: 'string',
          enum: ['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'],
          description: 'Override default model (defaults to sonar-deep-research)',
        },
        max_tokens: { type: 'number', minimum: 1, description: 'Maximum response length' },
      },
      required: ['topic'],
    },
  },
  {
    name: 'chat_perplexity',
    description: 'Maintain conversations with Perplexity stored in project directory.',
    inputSchema: {
      type: 'object',
      properties: {
        message: { type: 'string', description: 'Your message' },
        project_name: {
          type: 'string',
          description:
            'Project name for organizing conversations (auto-detected if not provided)',
        },
        chat_id: { type: 'string', description: 'Continue existing conversation' },
        title: { type: 'string', description: 'Required for new chat - conversation title' },
        model: {
          type: 'string',
          enum: ['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'],
          description: 'Override default model',
        },
        temperature: {
          type: 'number',
          minimum: 0,
          maximum: 1,
          description: '0.0-1.0, default 0.2',
        },
        max_tokens: { type: 'number', minimum: 1, description: 'Maximum response length' },
        save_report: { type: 'boolean', description: 'Save conversation to project directory' },
      },
      required: ['message'],
    },
  },
  {
    name: 'async_perplexity',
    description: 'Create async jobs for complex queries that may take longer to process.',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'Your question or prompt' },
        model: {
          type: 'string',
          enum: ['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'],
          description: 'Override default model',
        },
        temperature: {
          type: 'number',
          minimum: 0,
          maximum: 1,
          description: '0.0-1.0, default 0.2',
        },
        max_tokens: { type: 'number', minimum: 1, description: 'Maximum response length' },
      },
      required: ['query'],
    },
  },
  {
    name: 'check_async_perplexity',
    description: 'Check status and retrieve results of async Perplexity jobs.',
    inputSchema: {
      type: 'object',
      properties: {
        job_id: { type: 'string', description: 'Async job identifier' },
        include_content: {
          type: 'boolean',
          description: 'Include full response content (default: false to save context)',
        },
        save_report: {
          type: 'boolean',
          description: 'Save completed report to project directory (default: true)',
        },
        project_name: {
          type: 'string',
          description: 'Project name for saving report (auto-detected if not provided)',
        },
      },
      required: ['job_id'],
    },
  },
  {
    name: 'list_async_jobs',
    description: 'List all async Perplexity jobs with status and timing information.',
    inputSchema: {
      type: 'object',
      properties: {
        project_name: {
          type: 'string',
          description: 'Project name (auto-detected if not provided)',
        },
        limit: {
          type: 'number',
          minimum: 1,
          maximum: 100,
          description: 'Maximum number of jobs to return (default: 20)',
        },
        next_token: { type: 'string', description: 'Token for pagination' },
      },
    },
  },
  {
    name: 'list_chats_perplexity',
    description: 'List all conversations stored in the current project.',
    inputSchema: {
      type: 'object',
      properties: {
        project_name: {
          type: 'string',
          description: 'Project name (auto-detected if not provided)',
        },
      },
    },
  },
  {
    name: 'read_chat_perplexity',
    description: 'Retrieve complete conversation history from project storage.',
    inputSchema: {
      type: 'object',
      properties: {
        chat_id: { type: 'string', description: 'Conversation identifier' },
      },
      required: ['chat_id'],
    },
  },
  {
    name: 'storage_stats_perplexity',
    description: "Get storage statistics for the current project's Perplexity data.",
    inputSchema: {
      type: 'object',
      properties: {
        project_name: {
          type: 'string',
          description: 'Project name (auto-detected if not provided)',
        },
      },
    },
  },
  {
    name: 'list_projects_perplexity',
    description: 'List all existing projects with optional detailed statistics.',
    inputSchema: {
      type: 'object',
      properties: {
        detailed: {
          type: 'boolean',
          description: 'Include detailed statistics for each project',
        },
      },
    },
  },
  {
    name: 'delete_project_perplexity',
    description: 'Safely delete a project and all its data.',
    inputSchema: {
      type: 'object',
      properties: {
        project_name: {
          type: 'string',
          description: 'Name of the project to delete (all data will be permanently removed)',
        },
        confirm: {
          type: 'boolean',
          description: 'Confirmation that you want to permanently delete all project data',
        },
      },
      required: ['project_name', 'confirm'],
    },
  },
  {
    name: 'model_info_perplexity',
    description: 'Get detailed information about available Perplexity models.',
    inputSchema: {
      type: 'object',
      properties: {},
    },
  },
];

// Session configuration
const SESSION_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes of inactivity
const CLEANUP_INTERVAL_MS = 5 * 60 * 1000; // Check every 5 minutes

// Session data type - stores server, transport, and activity tracking
interface SessionData {
  server: Server;
  transport: StreamableHTTPServerTransport;
  lastActivity: number; // Unix timestamp in ms
  createdAt: number; // Unix timestamp in ms
}

/**
 * Factory function to create a new MCP Server instance with all handlers registered.
 * Each client session gets its own Server instance to avoid blocking.
 */
function createMCPServer(config: z.infer<typeof configSchema>): Server {
  const server = new Server(
    {
      name: 'mcp-perplexity-pro',
      version: '1.3.0',
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

  // List available tools
  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: TOOL_DEFINITIONS,
  }));

  // Handle tool calls
  server.setRequestHandler(CallToolRequestSchema, async (request): Promise<any> => {
    const { name, arguments: args } = request.params;

    try {
      switch (name) {
        case 'ask_perplexity': {
          // Enable streaming with MCP progress notifications and stdout output
          let chunkCount = 0;
          const streamingCallbacks = {
            onChunk: async (chunk: any) => {
              const content = chunk.choices?.[0]?.delta?.content;
              console.log('Streaming chunk received:', content || '[no content]');

              if (content) {
                chunkCount++;

                // Output to stdout for real-time display
                process.stdout.write(`[CHUNK ${chunkCount}]: ${content}`);

                // Send MCP progress notification (if supported by Claude Code)
                try {
                  await server.notification({
                    method: 'notifications/progress',
                    params: {
                      progressToken: 'streaming',
                      progress: Math.min(chunkCount * 2, 99), // Approximate progress
                      total: 100,
                      message: `Streaming content... (chunk ${chunkCount})`,
                    },
                  });
                } catch (progressError) {
                  console.log(
                    'Progress notification failed (expected):',
                    progressError instanceof Error ? progressError.message : String(progressError)
                  );
                }
              }
            },
            onComplete: async () => {
              console.log('Streaming complete');
              process.stdout.write(`\n[STREAMING COMPLETE]\n`);

              // Send final progress notification
              try {
                await server.notification({
                  method: 'notifications/progress',
                  params: {
                    progressToken: 'streaming',
                    progress: 100,
                    total: 100,
                    message: 'Streaming complete!',
                  },
                });
              } catch (progressError) {
                console.log(
                  'Final progress notification failed:',
                  progressError instanceof Error ? progressError.message : String(progressError)
                );
              }
            },
            onError: (error: Error) => {
              console.error('Streaming error:', error);
              process.stdout.write(`\n[STREAMING ERROR]: ${error.message}\n`);
            },
          };

          const result = await handleAskPerplexity(args as any, config, streamingCallbacks);
          return result;
        }

        case 'research_perplexity': {
          const result = await handleResearchPerplexity(args as any, config);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          };
        }

        case 'chat_perplexity': {
          const result = await handleChatPerplexity(args as any, config);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          };
        }

        case 'async_perplexity': {
          const result = await handleAsyncPerplexity(args as any, config);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          };
        }

        case 'check_async_perplexity': {
          const result = await handleCheckAsync(args as any, config);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          };
        }

        case 'list_async_jobs': {
          const result = await handleListAsyncJobs(
            config,
            (args as any)?.limit,
            (args as any)?.next_token
          );
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          };
        }

        case 'list_chats_perplexity': {
          const result = await handleListChats(config);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          };
        }

        case 'read_chat_perplexity': {
          const result = await handleReadChat(args as any, config);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          };
        }

        case 'storage_stats_perplexity': {
          const result = await handleStorageStats(config);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          };
        }

        case 'list_projects_perplexity': {
          const result = await handleListProjects(args as any, config);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          };
        }

        case 'delete_project_perplexity': {
          const result = await handleDeleteProject(args as any, config);
          return {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          };
        }

        case 'model_info_perplexity': {
          const modelInfo = {
            available_models: getModelSummary(),
            default_model: config.default_model,
            automatic_selection:
              'Enabled - models selected based on query complexity and requirements',
            override_capability:
              'All tools accept optional "model" parameter to override automatic selection',
            selection_factors: [
              'Query complexity and length',
              'Keywords indicating specific needs (research, analysis, etc.)',
              'Task type (facts vs reasoning vs research)',
              'Performance vs cost trade-offs',
            ],
          };
          return {
            content: [{ type: 'text', text: JSON.stringify(modelInfo, null, 2) }],
          };
        }

        default:
          throw new Error(`Unknown tool: ${name}`);
      }
    } catch (error) {
      return {
        content: [
          {
            type: 'text',
            text: `Error: ${error instanceof Error ? error.message : String(error)}`,
          },
        ],
        isError: true,
      };
    }
  });

  return server;
}

export function createHTTPStreamingServer(config: z.infer<typeof configSchema>) {
  // Session management - stores server, transport, and activity tracking per session
  const sessions: Record<string, SessionData> = {};

  /**
   * Clean up expired sessions to prevent memory leaks.
   * Removes sessions that haven't been active for SESSION_TIMEOUT_MS.
   */
  function cleanupExpiredSessions(): { removed: number; remaining: number } {
    const now = Date.now();
    const expiredSessions: string[] = [];

    for (const [sessionId, sessionData] of Object.entries(sessions)) {
      const inactiveTime = now - sessionData.lastActivity;
      if (inactiveTime > SESSION_TIMEOUT_MS) {
        expiredSessions.push(sessionId);
      }
    }

    // Remove expired sessions
    for (const sessionId of expiredSessions) {
      const sessionData = sessions[sessionId];
      try {
        // Close the server connection gracefully
        sessionData.server.close().catch((err: Error) => {
          console.log(`Error closing server for session ${sessionId}:`, err.message);
        });
      } catch (err) {
        console.log(`Error during session cleanup for ${sessionId}:`, err);
      }
      delete sessions[sessionId];
      console.log(`Session expired and cleaned up: ${sessionId} (inactive for ${Math.round((now - sessionData.lastActivity) / 1000 / 60)} minutes)`);
    }

    if (expiredSessions.length > 0) {
      console.log(`Session cleanup: removed ${expiredSessions.length} expired sessions, ${Object.keys(sessions).length} remaining`);
    }

    return { removed: expiredSessions.length, remaining: Object.keys(sessions).length };
  }

  // Start periodic cleanup
  const cleanupInterval = setInterval(() => {
    cleanupExpiredSessions();
  }, CLEANUP_INTERVAL_MS);

  // Log cleanup interval start
  console.log(`Session cleanup scheduled: checking every ${CLEANUP_INTERVAL_MS / 1000 / 60} minutes, timeout after ${SESSION_TIMEOUT_MS / 1000 / 60} minutes of inactivity`);

  // Clean up interval on process exit
  process.on('SIGTERM', () => {
    clearInterval(cleanupInterval);
    console.log('Cleanup interval cleared on SIGTERM');
  });
  process.on('SIGINT', () => {
    clearInterval(cleanupInterval);
    console.log('Cleanup interval cleared on SIGINT');
  });

  const app = express();
  app.use(express.json());

  // Configure CORS with required headers
  app.use(
    cors({
      origin: '*',
      exposedHeaders: ['Mcp-Session-Id'],
    })
  );

  // Add logging middleware
  app.use((req, res, next) => {
    console.log(`${new Date().toISOString()} - ${req.method} ${req.url}`);
    next();
  });

  // No authentication required - this is an authless MCP server

  // MCP endpoint with proper session management
  // Each session gets its own Server instance to support concurrent clients
  app.all('/mcp', async (req, res): Promise<void> => {
    console.log('MCP request received:', req.method, req.headers);

    try {
      const sessionId = req.headers['mcp-session-id'] as string | undefined;
      let sessionData: SessionData;

      if (sessionId && sessions[sessionId]) {
        // Reuse existing session (server + transport pair)
        sessionData = sessions[sessionId];
        // Update last activity timestamp
        sessionData.lastActivity = Date.now();
        console.log('Reusing existing session:', sessionId);
      } else if (sessionId && !sessions[sessionId]) {
        // Session ID provided but doesn't exist (expired/server restarted)
        // Return error so client knows to reinitialize
        console.log('Session expired or not found:', sessionId);
        res.status(404).json({
          jsonrpc: '2.0',
          error: {
            code: -32000,
            message: 'Session expired or not found. Please reinitialize.',
          },
          id: null,
        });
        return;
      } else if (req.method === 'POST') {
        // Create new session with its own Server instance (no session ID provided)
        console.log('Creating new session with dedicated Server instance');

        const now = Date.now();
        const server = createMCPServer(config);
        const transport = new StreamableHTTPServerTransport({
          sessionIdGenerator: () => randomUUID(),
          onsessioninitialized: newSessionId => {
            console.log('Session initialized:', newSessionId);
            // Store the session data after initialization with timestamps
            sessions[newSessionId] = {
              server,
              transport,
              lastActivity: now,
              createdAt: now,
            };
          },
        });

        // Connect this server to its transport
        await server.connect(transport);

        // Use temporary session data for the initial request
        sessionData = { server, transport, lastActivity: now, createdAt: now };
      } else {
        res.status(400).json({
          error: 'Session required',
          message: 'POST request required to initialize session',
        });
        return;
      }

      await sessionData.transport.handleRequest(req, res, req.body);
      return;
    } catch (error) {
      console.error('Error handling MCP request:', error);
      res.status(500).json({
        error: 'Internal server error',
        details: error instanceof Error ? error.message : String(error),
      });
      return;
    }
  });

  // Health check endpoint
  app.get('/health', (req, res) => {
    const now = Date.now();
    const sessionIds = Object.keys(sessions);
    const activeSessions = sessionIds.length;

    // Calculate session age statistics
    let oldestSession = 0;
    let newestSession = 0;
    let totalIdleTime = 0;

    for (const sessionId of sessionIds) {
      const session = sessions[sessionId];
      const age = now - session.createdAt;
      const idle = now - session.lastActivity;

      if (age > oldestSession) oldestSession = age;
      if (newestSession === 0 || age < newestSession) newestSession = age;
      totalIdleTime += idle;
    }

    res.json({
      status: 'healthy',
      transport: 'http-streaming',
      server: 'mcp-perplexity-pro',
      version: '1.3.0',
      active_sessions: activeSessions,
      session_timeout_minutes: SESSION_TIMEOUT_MS / 1000 / 60,
      cleanup_interval_minutes: CLEANUP_INTERVAL_MS / 1000 / 60,
      session_stats: activeSessions > 0 ? {
        oldest_session_minutes: Math.round(oldestSession / 1000 / 60),
        newest_session_minutes: Math.round(newestSession / 1000 / 60),
        avg_idle_minutes: Math.round(totalIdleTime / activeSessions / 1000 / 60),
      } : null,
    });
  });

  // Manual cleanup endpoint (for admin use)
  app.post('/cleanup', (req, res) => {
    const result = cleanupExpiredSessions();
    res.json({
      message: 'Cleanup completed',
      ...result,
    });
  });

  // Force cleanup all sessions endpoint (for admin use)
  app.post('/cleanup/all', (req, res) => {
    const sessionIds = Object.keys(sessions);
    const count = sessionIds.length;

    for (const sessionId of sessionIds) {
      const sessionData = sessions[sessionId];
      try {
        sessionData.server.close().catch((err: Error) => {
          console.log(`Error closing server for session ${sessionId}:`, err.message);
        });
      } catch (err) {
        console.log(`Error during forced cleanup for ${sessionId}:`, err);
      }
      delete sessions[sessionId];
    }

    console.log(`Forced cleanup: removed all ${count} sessions`);
    res.json({
      message: 'All sessions cleared',
      removed: count,
      remaining: 0,
    });
  });

  return app;
}
