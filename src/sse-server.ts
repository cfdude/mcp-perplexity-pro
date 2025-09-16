import express from 'express';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { SSEServerTransport } from '@modelcontextprotocol/sdk/server/sse.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { z } from 'zod';
import { configSchema } from './types.js';
import { handleAskPerplexity, handleResearchPerplexity } from './tools/query.js';
import { getModelSummary } from './models.js';

export function createSSEServer(config: z.infer<typeof configSchema>) {
  const server = new Server(
    {
      name: 'mcp-perplexity-pro',
      version: '1.0.0',
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

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
              description:
                'Project name for organizing conversations (auto-detected if not provided)',
            },
            model: {
              type: 'string',
              enum: [
                'sonar',
                'sonar-pro',
                'sonar-reasoning',
                'sonar-reasoning-pro',
                'sonar-deep-research',
              ],
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
              enum: [
                'sonar',
                'sonar-pro',
                'sonar-reasoning',
                'sonar-reasoning-pro',
                'sonar-deep-research',
              ],
              description: 'Override default model (defaults to sonar-deep-research)',
            },
            max_tokens: { type: 'number', minimum: 1, description: 'Maximum response length' },
          },
          required: ['topic'],
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

  // Handle tool calls
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

  const app = express();
  app.use(express.json());

  // Add logging middleware
  app.use((req, res, next) => {
    console.log(`${new Date().toISOString()} - ${req.method} ${req.url}`);
    next();
  });

  const transportMap = new Map<string, SSEServerTransport>();

  // OAuth endpoints for Claude Code compatibility
  app.post('/oauth/register', (req, res) => {
    console.log('OAuth register request received:', req.body);
    // Mock OAuth dynamic client registration
    res.json({
      client_id: 'perplexity-sse-client',
      client_secret: 'mock-secret',
      authorization_endpoint: `http://localhost:8124/oauth/authorize`,
      token_endpoint: `http://localhost:8124/oauth/token`,
    });
  });

  app.get('/oauth/authorize', (req, res) => {
    // Mock OAuth authorization - auto-approve for local development
    const { redirect_uri, state } = req.query;
    res.redirect(`${redirect_uri}?code=mock-auth-code&state=${state}`);
  });

  app.post('/oauth/token', (req, res) => {
    // Mock OAuth token exchange
    res.json({
      access_token: 'mock-access-token',
      token_type: 'Bearer',
      expires_in: 3600,
    });
  });

  // SSE endpoint for real-time streaming
  app.get('/sse', async (req, res) => {
    const transport = new SSEServerTransport('/messages', res);
    transportMap.set(transport.sessionId, transport);
    await server.connect(transport);
  });

  // Messages endpoint for handling POST requests
  app.post('/messages', (req, res) => {
    const sessionId = req.query.sessionId as string;
    if (!sessionId) {
      console.error('Message received without sessionId');
      res.status(400).json({ error: 'sessionId is required' });
      return;
    }

    const transport = transportMap.get(sessionId);

    if (transport) {
      transport.handlePostMessage(req, res);
    } else {
      res.status(404).json({ error: 'Session not found' });
    }
  });

  return app;
}
