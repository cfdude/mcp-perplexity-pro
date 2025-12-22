import { z } from 'zod';

// Perplexity model types
export type PerplexityModel = 'sonar' | 'sonar-pro' | 'sonar-reasoning-pro' | 'sonar-deep-research';

// Per-tool model configuration schema
const modelsConfigSchema = z.object({
  ask: z
    .enum(['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'])
    .default('sonar-reasoning-pro')
    .describe('Default model for ask_perplexity queries'),
  chat: z
    .enum(['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'])
    .default('sonar-pro')
    .describe('Default model for chat_perplexity conversations'),
  research: z
    .enum(['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'])
    .default('sonar-deep-research')
    .describe('Default model for research_perplexity reports'),
  async: z
    .enum(['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'])
    .default('sonar-reasoning-pro')
    .describe('Default model for async_perplexity jobs'),
});

// Configuration schema for MCP server
export const configSchema = z.object({
  api_key: z.string().describe('Perplexity API key'),
  default_model: z
    .enum(['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'])
    .default('sonar-reasoning-pro')
    .describe('Fallback default model for queries (used if per-tool model not specified)'),
  models: modelsConfigSchema
    .default({
      ask: 'sonar-reasoning-pro',
      chat: 'sonar-pro',
      research: 'sonar-deep-research',
      async: 'sonar-reasoning-pro',
    })
    .describe('Per-tool model defaults'),
  project_root: z.string().describe('Root directory of the calling project'),
  storage_path: z
    .string()
    .default('.perplexity/chat_history')
    .describe('Path relative to project_root for storing conversations'),
  session_id: z.string().optional().describe('Optional session identifier for thread safety'),
});

export type Config = z.infer<typeof configSchema>;

// Message types for conversations
export interface Message {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

// Extended message type with timestamp
export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
  timestamp: string;
}

// Chat completion request type
export interface ChatCompletionRequest {
  model: PerplexityModel;
  messages: Message[];
  temperature?: number;
  max_tokens?: number;
}

// Async chat request type
export interface AsyncChatRequest {
  model: PerplexityModel;
  messages: Message[];
  temperature?: number;
  max_tokens?: number;
}

// Async job report type
export interface AsyncJobReport {
  id: string;
  query: string;
  model: PerplexityModel;
  response?: string;
  created_at?: string;
  completed_at?: string;
}

// MCP response format
export interface MCPResponse {
  content: Array<{
    type: 'text';
    text: string;
  }>;
}

// Chat conversation metadata
export interface ChatMetadata {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  model: PerplexityModel;
}

// Full conversation with messages
export interface Conversation {
  metadata: ChatMetadata;
  messages: Message[];
}

// Perplexity API request parameters
export interface PerplexityRequest {
  model: PerplexityModel;
  messages: Message[];
  max_tokens?: number;
  temperature?: number;
  top_p?: number;
  search_domain_filter?: string[];
  return_images?: boolean;
  return_related_questions?: boolean;
  search_recency_filter?: string;
  search_after_date_filter?: string;
  search_before_date_filter?: string;
  last_updated_after_filter?: string;
  last_updated_before_filter?: string;
  top_k?: number;
  stream?: boolean;
  presence_penalty?: number;
  frequency_penalty?: number;
  response_format?: Record<string, unknown>;
  disable_search?: boolean;
  enable_search_classifier?: boolean;
  web_search_options?: {
    search_context_size?: 'low' | 'medium' | 'high';
  };
}

// Perplexity API response types
export interface SearchResult {
  title: string;
  url: string;
  date?: string;
}

export interface Usage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  search_context_size?: string;
  citation_tokens?: number;
  num_search_queries?: number;
  reasoning_tokens?: number;
}

export interface Choice {
  index: number;
  finish_reason: 'stop' | 'length' | 'content_filter';
  message: {
    role: 'assistant';
    content: string;
  };
}

export interface PerplexityResponse {
  id: string;
  model: string;
  created: number;
  usage: Usage;
  object: 'chat.completion';
  choices: Choice[];
  search_results?: SearchResult[];
}

// Streaming response types
export interface StreamChoice {
  index: number;
  finish_reason?: 'stop' | 'length' | 'content_filter';
  delta: {
    role?: 'assistant';
    content?: string;
  };
}

export interface PerplexityStreamChunk {
  id: string;
  model: string;
  created: number;
  object: 'chat.completion.chunk';
  choices: StreamChoice[];
  search_results?: SearchResult[];
  usage?: Usage;
}

// Streaming callback types
export type StreamingCallback = (chunk: PerplexityStreamChunk) => void;
export type StreamingCompleteCallback = (finalResponse: PerplexityResponse) => void;
export type StreamingErrorCallback = (error: Error) => void;

export interface StreamingCallbacks {
  onChunk?: StreamingCallback;
  onComplete?: StreamingCompleteCallback;
  onError?: StreamingErrorCallback;
}

// Async operation types
export interface AsyncJob {
  id: string;
  model: string;
  created_at: number;
  started_at?: number;
  completed_at?: number;
  response?: PerplexityResponse;
  failed_at?: number;
  error_message?: string;
  error?: string;
  status: 'CREATED' | 'STARTED' | 'COMPLETED' | 'FAILED';
  choices?: Choice[];
  usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
  estimated_completion?: string;
}

// Error response structure
export interface ErrorDetails {
  suggestion: string;
  fallback_model?: PerplexityModel;
  retry_after?: number;
  storage_path?: string;
}

export interface ErrorResponse {
  error: {
    type: 'rate_limit' | 'invalid_model' | 'api_error' | 'storage_error' | 'validation_error';
    message: string;
    details: ErrorDetails;
  };
}

// Model capability definitions
export interface ModelCapability {
  type: 'search' | 'reasoning' | 'research';
  speed: 'fast' | 'medium' | 'slow';
  cost: 'low' | 'medium' | 'high';
  bestFor: string[];
  description: string;
  capabilities: {
    search: boolean;
    reasoning: boolean;
    realTime: boolean;
    research: boolean;
  };
}

export type ModelRegistry = Record<PerplexityModel, ModelCapability>;

// Tool parameter schemas
export const askPerplexitySchema = z.object({
  query: z.string().describe('Your question or prompt'),
  project_name: z
    .string()
    .optional()
    .describe('Project name for organizing conversations (auto-detected if not provided)'),
  model: z
    .enum(['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'])
    .optional()
    .describe('Override default model'),
  temperature: z.number().min(0).max(1).optional().describe('0.0-1.0, default 0.2'),
  max_tokens: z.number().positive().optional().describe('Maximum response length'),
  search_domain_filter: z.array(z.string()).optional().describe('Limit search to specific domains'),
  return_images: z.boolean().optional().describe('Include images in response'),
  return_related_questions: z.boolean().optional().describe('Include related questions'),
  save_report: z.boolean().optional().describe('Save response as a report to project directory'),
});

export const chatPerplexitySchema = z.object({
  message: z.string().describe('Your message'),
  project_name: z
    .string()
    .optional()
    .describe('Project name for organizing conversations (auto-detected if not provided)'),
  chat_id: z.string().optional().describe('Continue existing conversation'),
  title: z.string().optional().describe('Required for new chat - conversation title'),
  model: z
    .enum(['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'])
    .optional()
    .describe('Override default model'),
  temperature: z.number().min(0).max(1).optional().describe('0.0-1.0, default 0.2'),
  max_tokens: z.number().positive().optional().describe('Maximum response length'),
  save_report: z.boolean().optional().describe('Save conversation to project directory'),
});

export const researchPerplexitySchema = z.object({
  topic: z.string().describe('Research topic or question'),
  project_name: z
    .string()
    .optional()
    .describe('Project name for organizing research reports (auto-detected if not provided)'),
  save_report: z.boolean().optional().describe('Save report to project directory'),
  model: z
    .enum(['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'])
    .optional()
    .describe('Override default model (defaults to sonar-deep-research)'),
  max_tokens: z.number().positive().optional().describe('Maximum response length'),
});

export const asyncPerplexitySchema = z.object({
  query: z.string().describe('Your question or prompt'),
  model: z
    .enum(['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'])
    .optional()
    .describe('Override default model'),
  temperature: z.number().min(0).max(1).optional().describe('0.0-1.0, default 0.2'),
  max_tokens: z.number().positive().optional().describe('Maximum response length'),
});

export const checkAsyncSchema = z.object({
  job_id: z.string().describe('Async job identifier'),
  include_content: z
    .boolean()
    .optional()
    .describe('Include full response content (default: false to save context)'),
  save_report: z
    .boolean()
    .optional()
    .describe('Save completed report to project directory (default: true)'),
  project_name: z
    .string()
    .optional()
    .describe('Project name for saving report (auto-detected if not provided)'),
});

export const readChatSchema = z.object({
  chat_id: z.string().describe('Conversation identifier'),
});

// Project management schemas
export const listProjectsSchema = z.object({
  detailed: z.boolean().optional().describe('Include detailed statistics for each project'),
});

export const deleteProjectSchema = z.object({
  project_name: z
    .string()
    .describe('Name of the project to delete (all data will be permanently removed)'),
  confirm: z
    .boolean()
    .describe('Confirmation that you want to permanently delete all project data'),
});

export type AskPerplexityParams = z.infer<typeof askPerplexitySchema>;
export type ChatPerplexityParams = z.infer<typeof chatPerplexitySchema>;
export type ResearchPerplexityParams = z.infer<typeof researchPerplexitySchema>;
export type AsyncPerplexityParams = z.infer<typeof asyncPerplexitySchema>;
export type CheckAsyncParams = z.infer<typeof checkAsyncSchema>;
export type ReadChatParams = z.infer<typeof readChatSchema>;
export type ListProjectsParams = z.infer<typeof listProjectsSchema>;
export type DeleteProjectParams = z.infer<typeof deleteProjectSchema>;
