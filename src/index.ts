import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import {
  configSchema,
  askPerplexitySchema,
  chatPerplexitySchema,
  researchPerplexitySchema,
  asyncPerplexitySchema,
  checkAsyncSchema,
  readChatSchema,
} from './types.js';
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
import { getModelSummary } from './models.js';

// Export configuration schema for Smithery
export { configSchema };

export default function createServer({ config }: { config: z.infer<typeof configSchema> }) {
  const server = new McpServer({
    name: 'mcp-perplexity-pro',
    version: '1.0.0',
  });

  // Tool: ask_perplexity - Stateless query with intelligent model selection
  server.tool(
    'ask_perplexity',
    `Query Perplexity with automatic model selection based on complexity.

**Model Selection:**
- sonar: Quick facts, simple queries, basic summaries
- sonar-pro: Complex queries, follow-ups, detailed summaries  
- sonar-reasoning: Problem-solving, analysis, step-by-step thinking
- sonar-reasoning-pro: Complex analysis, detailed reasoning, multi-step problems
- sonar-deep-research: Comprehensive reports, exhaustive research, literature reviews

**Default:** sonar-reasoning-pro for balanced performance
**Override:** Use 'model' parameter to specify a different model

Returns response with citations and search results when available.`,
    askPerplexitySchema.shape,
    async params => {
      const result = await handleAskPerplexity(params, config);
      return {
        content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // Tool: chat_perplexity - Conversational interface with storage
  server.tool(
    'chat_perplexity',
    `Maintain conversations with Perplexity stored in project directory.

**Usage:**
- New chat: Provide 'message' and 'title'
- Continue chat: Provide 'message' and 'chat_id'

**Storage:** Saves conversations to {project_root}/{storage_path}/
**Model Selection:** Automatically selects optimal model for new chats, or specify with 'model' parameter

Returns response with chat_id for continuation and conversation metadata.`,
    chatPerplexitySchema.shape,
    async params => {
      const result = await handleChatPerplexity(params, config);
      return {
        content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // Tool: research_perplexity - Deep research with optional saving
  server.tool(
    'research_perplexity',
    `Conduct comprehensive research using sonar-deep-research model (or override).

**Features:**
- Optimized for exhaustive research and detailed reports
- Optional report saving to project directory
- Enhanced search context and citations
- Multiple perspectives and source analysis

**Best for:** Market analysis, literature reviews, comprehensive topic reports

Returns detailed research with citations, optionally saved as markdown report.`,
    researchPerplexitySchema.shape,
    async params => {
      const result = await handleResearchPerplexity(params, config);
      return {
        content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // Tool: async_perplexity - Create async jobs for long-running queries
  server.tool(
    'async_perplexity',
    `Create async jobs for complex queries that may take longer to process.

**When to use:**
- Complex research requiring extensive search
- Rate limit mitigation
- Non-urgent queries
- Batch processing

**Features:**
- Immediate job ID return
- Estimated completion time
- Status tracking with check_async_perplexity

Returns job information with estimated completion time.`,
    asyncPerplexitySchema.shape,
    async params => {
      const result = await handleAsyncPerplexity(params, config);
      return {
        content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // Tool: check_async_perplexity - Check status of async jobs
  server.tool(
    'check_async_perplexity',
    `Check status and retrieve results of async Perplexity jobs.

**Status types:**
- CREATED: Job queued, not started
- STARTED: Job in progress  
- COMPLETED: Job finished, results available
- FAILED: Job failed, error details provided

Returns job status with completion percentage and next check recommendation.`,
    checkAsyncSchema.shape,
    async params => {
      const result = await handleCheckAsync(params, config);
      return {
        content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // Tool: list_async_jobs - List all async jobs
  server.tool(
    'list_async_jobs',
    `List all async Perplexity jobs with status and timing information.

**Information provided:**
- Job status and progress
- Time since creation
- Estimated time remaining for active jobs
- Model used and creation details

Useful for monitoring multiple research tasks and managing workload.`,
    {
      limit: z.number().min(1).max(100).optional().describe('Maximum number of jobs to return (default: 20)'),
      next_token: z.string().optional().describe('Token for pagination'),
    },
    async params => {
      const result = await handleListAsyncJobs(config, params.limit, params.next_token);
      return {
        content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // Tool: list_chats_perplexity - List all conversations
  server.tool(
    'list_chats_perplexity',
    `List all conversations stored in the current project.

**Information provided:**
- Chat ID, title, and creation/update times
- Message count and model used
- Sorted by most recent activity

**Storage location:** {project_root}/{storage_path}/

Useful for finding and resuming previous conversations.`,
    {},
    async () => {
      const result = await handleListChats(config);
      return {
        content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // Tool: read_chat_perplexity - Retrieve conversation history
  server.tool(
    'read_chat_perplexity',
    `Retrieve complete conversation history from project storage.

**Usage:**
- Provide chat_id from list_chats_perplexity
- Returns full message history with metadata
- Useful for context review and conversation analysis

Returns complete conversation with all messages and metadata.`,
    readChatSchema.shape,
    async params => {
      const result = await handleReadChat(params, config);
      return {
        content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // Tool: storage_stats_perplexity - Get project storage statistics
  server.tool(
    'storage_stats_perplexity',
    `Get storage statistics for the current project's Perplexity data.

**Information provided:**
- Total conversations and messages
- Storage size in bytes
- Last activity timestamp
- Storage path location

Useful for understanding project usage and managing storage.`,
    {},
    async () => {
      const result = await handleStorageStats(config);
      return {
        content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
      };
    }
  );

  // Tool: model_info_perplexity - Get information about available models
  server.tool(
    'model_info_perplexity',
    `Get detailed information about available Perplexity models.

**Model Categories:**
- **Search Models:** sonar, sonar-pro (information retrieval and synthesis)
- **Reasoning Models:** sonar-reasoning, sonar-reasoning-pro (complex analysis and problem-solving)  
- **Research Models:** sonar-deep-research (comprehensive reports and investigations)

**Selection Guidance:**
- Speed vs Quality trade-offs
- Cost considerations  
- Use case recommendations
- Model capabilities and limitations

Returns comprehensive model information and selection guidance.`,
    {},
    async () => {
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
  );

  return server.server;
}