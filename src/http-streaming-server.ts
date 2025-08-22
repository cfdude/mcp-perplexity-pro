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

export function createHTTPStreamingServer(config: z.infer<typeof configSchema>) {
  // Session management
  const transports: Record<string, StreamableHTTPServerTransport> = {};

  const server = new Server({
    name: 'mcp-perplexity-pro',
    version: '1.0.0',
  }, {
    capabilities: {
      tools: {},
    },
  });

  // List available tools
  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [
      {
        name: 'ask_perplexity',
        description: 'Query Perplexity with automatic model selection based on complexity.',
        inputSchema: {
          type: 'object',
          properties: {
            query: { type: 'string', description: 'Your question or prompt' },
            project_name: {
              type: 'string',
              description: 'Project name for organizing conversations (auto-detected if not provided)',
            },
            model: {
              type: 'string',
              enum: ['sonar', 'sonar-pro', 'sonar-reasoning', 'sonar-reasoning-pro', 'sonar-deep-research'],
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
            save_report: { type: 'boolean', description: 'Save response as a report to project directory' },
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
              description: 'Project name for organizing research reports (auto-detected if not provided)',
            },
            save_report: { type: 'boolean', description: 'Save report to project directory' },
            model: {
              type: 'string',
              enum: ['sonar', 'sonar-pro', 'sonar-reasoning', 'sonar-reasoning-pro', 'sonar-deep-research'],
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
              description: 'Project name for organizing conversations (auto-detected if not provided)',
            },
            chat_id: { type: 'string', description: 'Continue existing conversation' },
            title: { type: 'string', description: 'Required for new chat - conversation title' },
            model: {
              type: 'string',
              enum: ['sonar', 'sonar-pro', 'sonar-reasoning', 'sonar-reasoning-pro', 'sonar-deep-research'],
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
              enum: ['sonar', 'sonar-pro', 'sonar-reasoning', 'sonar-reasoning-pro', 'sonar-deep-research'],
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
    ],
  }));

  // Handle tool calls with streaming support
  server.setRequestHandler(CallToolRequestSchema, async (request): Promise<any> => {
    const { name, arguments: args } = request.params;

    try {
      switch (name) {
        case 'ask_perplexity': {
          const result = await handleAskPerplexity(args as any, config);
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
            automatic_selection: 'Enabled - models selected based on query complexity and requirements',
            override_capability: 'All tools accept optional "model" parameter to override automatic selection',
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

  const app = express();
  app.use(express.json());

  // Configure CORS with required headers
  app.use(cors({
    origin: '*',
    exposedHeaders: ['Mcp-Session-Id']
  }));

  // Add logging middleware
  app.use((req, res, next) => {
    console.log(`${new Date().toISOString()} - ${req.method} ${req.url}`);
    next();
  });

  // No authentication required - this is an authless MCP server

  // MCP endpoint with proper session management
  app.all('/mcp', async (req, res): Promise<void> => {
    console.log('MCP request received:', req.method, req.headers);
    
    try {
      const sessionId = req.headers['mcp-session-id'] as string | undefined;
      let transport: StreamableHTTPServerTransport;

      if (sessionId && transports[sessionId]) {
        // Reuse existing transport for this session
        transport = transports[sessionId];
        console.log('Reusing existing transport for session:', sessionId);
      } else if (req.method === 'POST') {
        // Create new transport for new session
        console.log('Creating new transport for session');
        transport = new StreamableHTTPServerTransport({
          sessionIdGenerator: () => randomUUID(),
          onsessioninitialized: (newSessionId) => {
            console.log('Session initialized:', newSessionId);
            transports[newSessionId] = transport;
          }
        });
        await server.connect(transport);
      } else {
        res.status(400).json({
          error: 'Session required',
          message: 'POST request required to initialize session'
        });
        return;
      }

      await transport.handleRequest(req, res, req.body);
      return;
    } catch (error) {
      console.error('Error handling MCP request:', error);
      res.status(500).json({ 
        error: 'Internal server error',
        details: error instanceof Error ? error.message : String(error)
      });
      return;
    }
  });

  // Health check endpoint
  app.get('/health', (req, res) => {
    res.json({ 
      status: 'healthy', 
      transport: 'http-streaming',
      server: 'mcp-perplexity-pro',
      version: '1.0.0'
    });
  });

  return app;
}