#!/usr/bin/env node

/**
 * Stdio-only entry point for Claude Desktop and other stdio-based MCP clients
 * This bypasses the HTTP launcher and starts directly with stdio transport
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
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

// Smart project root detection for MCP servers
function detectProjectRoot(): string {
  const cwd = process.cwd();

  // If we're running from filesystem root or system directories,
  // use the user's home directory instead
  if (
    cwd === '/' ||
    cwd.startsWith('/usr/') ||
    cwd.startsWith('/opt/') ||
    cwd.startsWith('/var/')
  ) {
    return process.env.HOME || process.env.USERPROFILE || cwd;
  }

  // For other cases, use the current working directory
  return cwd;
}

// Load configuration - try multiple sources for API key
const apiKey =
  process.env.PERPLEXITY_API_KEY || process.env.API_KEY || process.env.PERPLEXITY_API_TOKEN || '';

const config = {
  api_key: apiKey,
  default_model: (process.env.DEFAULT_MODEL as any) || ('sonar-reasoning-pro' as const),
  project_root: process.env.PROJECT_ROOT || detectProjectRoot(),
  storage_path: process.env.STORAGE_PATH || '.perplexity',
  session_id: process.env.SESSION_ID,
};

// Validate configuration
const validatedConfig = configSchema.parse(config);

// Create MCP server
const server = new Server(
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

// Register tools
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: 'ask_perplexity',
        description: 'Query Perplexity AI with intelligent model selection for your questions.',
        inputSchema: {
          type: 'object',
          properties: {
            query: { type: 'string', description: 'Your question or prompt' },
            project_name: {
              type: 'string',
              description: 'Project name for organizing data (auto-detected if not provided)',
            },
            model: {
              type: 'string',
              enum: ['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'],
              description: 'Override default model selection',
            },
            temperature: {
              type: 'number',
              minimum: 0,
              maximum: 1,
              description: 'Sampling temperature (0.0-1.0, default: 0.2)',
            },
            max_tokens: { type: 'number', minimum: 1, description: 'Maximum response length' },
            save_report: { type: 'boolean', description: 'Save response to project directory' },
          },
          required: ['query'],
        },
      },
      {
        name: 'research_perplexity',
        description: 'Conduct comprehensive research with Perplexity and save detailed reports.',
        inputSchema: {
          type: 'object',
          properties: {
            topic: { type: 'string', description: 'Research topic or question' },
            project_name: {
              type: 'string',
              description: 'Project name for organizing reports (auto-detected if not provided)',
            },
            model: {
              type: 'string',
              enum: ['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'],
              description: 'Defaults to sonar-deep-research for comprehensive research',
            },
            save_report: { type: 'boolean', description: 'Save research report (default: true)' },
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
            project_name: {
              type: 'string',
              description: 'Project name for organizing data (auto-detected if not provided)',
            },
          },
          required: ['query'],
        },
      },
      {
        name: 'check_async_perplexity',
        description: 'Check the status of an async job and retrieve results if complete.',
        inputSchema: {
          type: 'object',
          properties: {
            job_id: { type: 'string', description: 'Job ID returned from async_perplexity' },
          },
          required: ['job_id'],
        },
      },
      {
        name: 'list_async_jobs',
        description: 'List all async jobs and their current status.',
        inputSchema: {
          type: 'object',
          properties: {
            limit: {
              type: 'number',
              minimum: 1,
              maximum: 50,
              description: 'Number of jobs to return',
            },
            project_name: {
              type: 'string',
              description: 'Filter by project (auto-detected if not provided)',
            },
          },
        },
      },
      {
        name: 'list_chats_perplexity',
        description: 'List all stored conversations in your project.',
        inputSchema: {
          type: 'object',
          properties: {
            project_name: {
              type: 'string',
              description: 'Project name to list chats from (auto-detected if not provided)',
            },
          },
        },
      },
      {
        name: 'read_chat_perplexity',
        description: 'Read the full conversation history from a stored chat.',
        inputSchema: {
          type: 'object',
          properties: {
            chat_id: { type: 'string', description: 'Chat ID to retrieve' },
            project_name: {
              type: 'string',
              description: 'Project name (auto-detected if not provided)',
            },
          },
          required: ['chat_id'],
        },
      },
      {
        name: 'storage_stats_perplexity',
        description: 'Get storage usage statistics for your projects.',
        inputSchema: {
          type: 'object',
          properties: {
            project_name: {
              type: 'string',
              description: 'Specific project to analyze (all projects if not provided)',
            },
          },
        },
      },
      {
        name: 'list_projects_perplexity',
        description: 'List all projects with their conversation and report counts.',
        inputSchema: {
          type: 'object',
          properties: {},
        },
      },
      {
        name: 'delete_project_perplexity',
        description: 'Safely delete a project and all its data after confirmation.',
        inputSchema: {
          type: 'object',
          properties: {
            project_name: { type: 'string', description: 'Project name to delete' },
            confirm: {
              type: 'boolean',
              description: 'Must be true to confirm deletion - this action cannot be undone',
            },
          },
          required: ['project_name', 'confirm'],
        },
      },
      {
        name: 'model_info_perplexity',
        description: 'Get information about available Perplexity models and selection guidance.',
        inputSchema: {
          type: 'object',
          properties: {},
        },
      },
    ],
  };
});

// Register tool call handler
server.setRequestHandler(CallToolRequestSchema, async request => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case 'ask_perplexity': {
        const result = await handleAskPerplexity(args as any, validatedConfig);
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
        };
      }

      case 'research_perplexity': {
        const result = await handleResearchPerplexity(args as any, validatedConfig);
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
        };
      }

      case 'chat_perplexity': {
        const result = await handleChatPerplexity(args as any, validatedConfig);
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
        };
      }

      case 'list_chats_perplexity': {
        const result = await handleListChats(validatedConfig);
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
        };
      }

      case 'read_chat_perplexity': {
        const result = await handleReadChat(args as any, validatedConfig);
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
        };
      }

      case 'async_perplexity': {
        const result = await handleAsyncPerplexity(args as any, validatedConfig);
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
        };
      }

      case 'check_async_perplexity': {
        const result = await handleCheckAsync(args as any, validatedConfig);
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
        };
      }

      case 'list_async_jobs': {
        const jobArgs = args as any;
        const result = await handleListAsyncJobs(
          validatedConfig,
          jobArgs?.limit,
          jobArgs?.next_token
        );
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
        };
      }

      case 'storage_stats_perplexity': {
        const result = await handleStorageStats(validatedConfig);
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
        };
      }

      case 'list_projects_perplexity': {
        const result = await handleListProjects(args as any, validatedConfig);
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
        };
      }

      case 'delete_project_perplexity': {
        const result = await handleDeleteProject(args as any, validatedConfig);
        return {
          content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
        };
      }

      case 'model_info_perplexity': {
        const modelInfo = {
          available_models: getModelSummary(),
          default_model: validatedConfig.default_model,
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

// Start the server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch(error => {
  console.error('Failed to start stdio MCP server:', error);
  process.exit(1);
});
