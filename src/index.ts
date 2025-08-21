#!/usr/bin/env node

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
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
import {
  handleAsyncPerplexity,
  handleCheckAsync,
  handleListAsyncJobs,
} from './tools/async.js';
import { handleListProjects, handleDeleteProject } from './tools/projects.js';
import { getModelSummary } from './models.js';

// Export configuration schema for Smithery
export { configSchema };

export class PerplexityServer {
  private server: Server;

  constructor(private config: z.infer<typeof configSchema>) {
    this.server = new Server(
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

    this.setupHandlers();
  }

  private setupHandlers() {
    // List available tools
    this.server.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: [
        {
          name: 'ask_perplexity',
          description: 'Query Perplexity with automatic model selection based on complexity.',
          inputSchema: {
            type: 'object',
            properties: {
              query: { type: 'string', description: 'Your question or prompt' },
              project_name: { type: 'string', description: 'Project name for organizing conversations (auto-detected if not provided)' },
              model: { type: 'string', enum: ['sonar', 'sonar-pro', 'sonar-reasoning', 'sonar-reasoning-pro', 'sonar-deep-research'], description: 'Override default model' },
              temperature: { type: 'number', minimum: 0, maximum: 1, description: '0.0-1.0, default 0.2' },
              max_tokens: { type: 'number', minimum: 1, description: 'Maximum response length' },
              search_domain_filter: { type: 'array', items: { type: 'string' }, description: 'Limit search to specific domains' },
              return_images: { type: 'boolean', description: 'Include images in response' },
              return_related_questions: { type: 'boolean', description: 'Include related questions' },
            },
            required: ['query'],
          },
        },
        {
          name: 'chat_perplexity',
          description: 'Maintain conversations with Perplexity stored in project directory.',
          inputSchema: {
            type: 'object',
            properties: {
              message: { type: 'string', description: 'Your message' },
              project_name: { type: 'string', description: 'Project name for organizing conversations (auto-detected if not provided)' },
              chat_id: { type: 'string', description: 'Continue existing conversation' },
              title: { type: 'string', description: 'Required for new chat - conversation title' },
              model: { type: 'string', enum: ['sonar', 'sonar-pro', 'sonar-reasoning', 'sonar-reasoning-pro', 'sonar-deep-research'], description: 'Override default model' },
              temperature: { type: 'number', minimum: 0, maximum: 1, description: '0.0-1.0, default 0.2' },
              max_tokens: { type: 'number', minimum: 1, description: 'Maximum response length' },
            },
            required: ['message'],
          },
        },
        {
          name: 'research_perplexity',
          description: 'Conduct comprehensive research using sonar-deep-research model.',
          inputSchema: {
            type: 'object',
            properties: {
              topic: { type: 'string', description: 'Research topic or question' },
              project_name: { type: 'string', description: 'Project name for organizing research reports (auto-detected if not provided)' },
              save_report: { type: 'boolean', description: 'Save report to project directory' },
              model: { type: 'string', enum: ['sonar', 'sonar-pro', 'sonar-reasoning', 'sonar-reasoning-pro', 'sonar-deep-research'], description: 'Override default model (defaults to sonar-deep-research)' },
              max_tokens: { type: 'number', minimum: 1, description: 'Maximum response length' },
            },
            required: ['topic'],
          },
        },
        {
          name: 'async_perplexity',
          description: 'Create async jobs for complex queries that may take longer to process.',
          inputSchema: {
            type: 'object',
            properties: {
              query: { type: 'string', description: 'Your question or prompt' },
              model: { type: 'string', enum: ['sonar', 'sonar-pro', 'sonar-reasoning', 'sonar-reasoning-pro', 'sonar-deep-research'], description: 'Override default model' },
              temperature: { type: 'number', minimum: 0, maximum: 1, description: '0.0-1.0, default 0.2' },
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
              project_name: { type: 'string', description: 'Project name (auto-detected if not provided)' },
              limit: { type: 'number', minimum: 1, maximum: 100, description: 'Maximum number of jobs to return (default: 20)' },
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
              project_name: { type: 'string', description: 'Project name (auto-detected if not provided)' },
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
          description: 'Get storage statistics for the current project\'s Perplexity data.',
          inputSchema: {
            type: 'object',
            properties: {
              project_name: { type: 'string', description: 'Project name (auto-detected if not provided)' },
            },
          },
        },
        {
          name: 'list_projects_perplexity',
          description: 'List all existing projects with optional detailed statistics.',
          inputSchema: {
            type: 'object',
            properties: {
              detailed: { type: 'boolean', description: 'Include detailed statistics for each project' },
            },
          },
        },
        {
          name: 'delete_project_perplexity',
          description: 'Safely delete a project and all its data.',
          inputSchema: {
            type: 'object',
            properties: {
              project_name: { type: 'string', description: 'Name of the project to delete (all data will be permanently removed)' },
              confirm: { type: 'boolean', description: 'Confirmation that you want to permanently delete all project data' },
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

    // Handle tool calls
    this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      const { name, arguments: args } = request.params;

      try {
        switch (name) {
          case 'ask_perplexity': {
            const result = await handleAskPerplexity(args as any, this.config);
            return {
              content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            };
          }

          case 'chat_perplexity': {
            const result = await handleChatPerplexity(args as any, this.config);
            return {
              content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            };
          }

          case 'research_perplexity': {
            const result = await handleResearchPerplexity(args as any, this.config);
            return {
              content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            };
          }

          case 'async_perplexity': {
            const result = await handleAsyncPerplexity(args as any, this.config);
            return {
              content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            };
          }

          case 'check_async_perplexity': {
            const result = await handleCheckAsync(args as any, this.config);
            return {
              content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            };
          }

          case 'list_async_jobs': {
            const result = await handleListAsyncJobs(this.config, (args as any)?.limit, (args as any)?.next_token);
            return {
              content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            };
          }

          case 'list_chats_perplexity': {
            const result = await handleListChats(this.config);
            return {
              content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            };
          }

          case 'read_chat_perplexity': {
            const result = await handleReadChat(args as any, this.config);
            return {
              content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            };
          }

          case 'storage_stats_perplexity': {
            const result = await handleStorageStats(this.config);
            return {
              content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            };
          }

          case 'list_projects_perplexity': {
            const result = await handleListProjects(args as any, this.config);
            return {
              content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            };
          }

          case 'delete_project_perplexity': {
            const result = await handleDeleteProject(args as any, this.config);
            return {
              content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
            };
          }

          case 'model_info_perplexity': {
            const modelInfo = {
              available_models: getModelSummary(),
              default_model: this.config.default_model,
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
          content: [{ type: 'text', text: `Error: ${error instanceof Error ? error.message : String(error)}` }],
          isError: true,
        };
      }
    });
  }

  async run() {
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
  }
}

// Main execution for stdio transport
if (import.meta.url === `file://${process.argv[1]}`) {
  const config = {
    api_key: process.env.PERPLEXITY_API_KEY || '',
    default_model: 'sonar-reasoning-pro' as const,
    project_root: process.cwd(),
    storage_path: '.perplexity',
  };

  const server = new PerplexityServer(config);
  server.run().catch((error: unknown) => {
    console.error('Failed to start server:', error);
    process.exit(1);
  });
}