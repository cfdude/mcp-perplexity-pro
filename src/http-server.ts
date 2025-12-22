#!/usr/bin/env node

import { Request, Response } from 'express';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import {
  LoggingMessageNotification,
  JSONRPCNotification,
  CallToolRequestSchema,
  ListToolsRequestSchema,
  InitializeRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import { randomUUID } from 'crypto';
import { configSchema } from './types.js';
import { z } from 'zod';
import { handleAskPerplexity, handleResearchPerplexity } from './tools/query.js';
import { handleChatPerplexity } from './tools/chat.js';

const SESSION_ID_HEADER_NAME = 'mcp-session-id';
const JSON_RPC = '2.0';

export class PerplexityHTTPServer {
  server: Server;
  transports: { [sessionId: string]: StreamableHTTPServerTransport } = {};

  constructor(private config: z.infer<typeof configSchema>) {
    this.server = new Server(
      {
        name: 'mcp-perplexity-pro',
        version: '1.0.0',
      },
      {
        capabilities: {
          tools: {},
          logging: {},
        },
      }
    );

    this.setupHandlers();
  }

  async handleGetRequest(req: Request, res: Response) {
    const sessionId = req.headers['mcp-session-id'] as string | undefined;
    if (!sessionId || !this.transports[sessionId]) {
      res.status(400).json(this.createErrorResponse('Bad Request: invalid session ID or method.'));
      return;
    }

    console.log(`Establishing SSE stream for session ${sessionId}`);
    const transport = this.transports[sessionId];
    await transport.handleRequest(req, res);

    return;
  }

  async handlePostRequest(req: Request, res: Response) {
    const sessionId = req.headers[SESSION_ID_HEADER_NAME] as string | undefined;
    let transport: StreamableHTTPServerTransport;

    try {
      // reuse existing transport
      if (sessionId && this.transports[sessionId]) {
        transport = this.transports[sessionId];
        await transport.handleRequest(req, res, req.body);
        return;
      }

      // create new transport
      if (!sessionId && this.isInitializeRequest(req.body)) {
        const transport = new StreamableHTTPServerTransport({
          sessionIdGenerator: () => randomUUID(),
        });

        await this.server.connect(transport);
        await transport.handleRequest(req, res, req.body);

        // session ID will only be available after handling the first request
        const sessionId = transport.sessionId;
        if (sessionId) {
          this.transports[sessionId] = transport;
        }

        return;
      }

      res.status(400).json(this.createErrorResponse('Bad Request: invalid session ID or method.'));
      return;
    } catch (error) {
      console.error('Error handling MCP request:', error);
      res.status(500).json(this.createErrorResponse('Internal server error.'));
      return;
    }
  }

  async cleanup() {
    await this.server.close();
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
              query: {
                type: 'string',
                description: 'The question or topic to research',
              },
              model: {
                type: 'string',
                description: 'Override default model selection',
                enum: ['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'],
              },
              max_tokens: {
                type: 'number',
                description: 'Maximum response length',
                minimum: 1,
              },
              temperature: {
                type: 'number',
                description: '0.0-1.0, default 0.2',
                minimum: 0,
                maximum: 1,
              },
              search_domain_filter: {
                type: 'array',
                items: { type: 'string' },
                description: 'Limit search to specific domains',
              },
              return_images: {
                type: 'boolean',
                description: 'Include images in response',
              },
              return_related_questions: {
                type: 'boolean',
                description: 'Include related questions',
              },
              save_report: {
                type: 'boolean',
                description: 'Save response as a report to project directory',
              },
              project_name: {
                type: 'string',
                description:
                  'Project name for organizing conversations (auto-detected if not provided)',
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
              topic: {
                type: 'string',
                description: 'Research topic or question',
              },
              model: {
                type: 'string',
                description: 'Override default model (defaults to sonar-deep-research)',
                enum: ['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'],
              },
              max_tokens: {
                type: 'number',
                description: 'Maximum response length',
                minimum: 1,
              },
              save_report: {
                type: 'boolean',
                description: 'Save report to project directory',
              },
              project_name: {
                type: 'string',
                description:
                  'Project name for organizing research reports (auto-detected if not provided)',
              },
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
              message: {
                type: 'string',
                description: 'Your message',
              },
              chat_id: {
                type: 'string',
                description: 'Continue existing conversation',
              },
              title: {
                type: 'string',
                description: 'Required for new chat - conversation title',
              },
              model: {
                type: 'string',
                description: 'Override default model',
                enum: ['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'],
              },
              max_tokens: {
                type: 'number',
                description: 'Maximum response length',
                minimum: 1,
              },
              temperature: {
                type: 'number',
                description: '0.0-1.0, default 0.2',
                minimum: 0,
                maximum: 1,
              },
              save_report: {
                type: 'boolean',
                description: 'Save conversation to project directory',
              },
              project_name: {
                type: 'string',
                description:
                  'Project name for organizing conversations (auto-detected if not provided)',
              },
            },
            required: ['message'],
          },
        },
        // ... include other tools as needed
      ],
    }));

    // Handle tool calls with streaming support
    this.server.setRequestHandler(CallToolRequestSchema, async (request, extra) => {
      const args = request.params.arguments;
      const toolName = request.params.name;

      if (!args || !toolName) {
        throw new Error('Invalid tool call');
      }

      // Get the transport for streaming
      const sessionId = (extra as any)?.sessionId;
      const transport = sessionId ? this.transports[sessionId] : null;

      try {
        switch (toolName) {
          case 'ask_perplexity': {
            if (transport) {
              // Stream the response in real-time
              return await this.handleStreamingTool(
                transport,
                'ask_perplexity',
                args,
                handleAskPerplexity
              );
            } else {
              // Fallback to regular response
              return await handleAskPerplexity(args as any, this.config);
            }
          }

          case 'research_perplexity': {
            if (transport) {
              return await this.handleStreamingTool(
                transport,
                'research_perplexity',
                args,
                handleResearchPerplexity
              );
            } else {
              return await handleResearchPerplexity(args as any, this.config);
            }
          }

          case 'chat_perplexity': {
            if (transport) {
              return await this.handleStreamingTool(
                transport,
                'chat_perplexity',
                args,
                handleChatPerplexity
              );
            } else {
              const result = await handleChatPerplexity(args as any, this.config);
              return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
            }
          }

          // Add other tool handlers here...
          default:
            throw new Error(`Unknown tool: ${toolName}`);
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
  }

  /**
   * Handle a tool call with streaming LoggingMessageNotifications
   */
  private async handleStreamingTool(
    transport: StreamableHTTPServerTransport,
    toolName: string,
    args: any,
    handler: Function
  ): Promise<any> {
    try {
      // Send initial streaming message
      await this.sendStreamingMessage(transport, `🚀 Starting ${toolName}...`);

      // Execute the tool handler
      const result = await handler(args, this.config);

      // Stream the result content
      if (result && typeof result === 'object' && result.content) {
        for (const contentItem of result.content) {
          if (contentItem.type === 'text') {
            // Split long text into chunks for better streaming experience
            const chunks = this.chunkText(contentItem.text, 500);
            for (const chunk of chunks) {
              await this.sendStreamingMessage(transport, chunk);
              // Small delay to create streaming effect
              await new Promise(resolve => setTimeout(resolve, 100));
            }
          }
        }
      }

      // Send completion message
      await this.sendStreamingMessage(transport, '✅ Complete!');

      return result;
    } catch (error) {
      await this.sendStreamingMessage(
        transport,
        `❌ Error: ${error instanceof Error ? error.message : String(error)}`
      );
      throw error;
    }
  }

  /**
   * Send a streaming message notification
   */
  private async sendStreamingMessage(
    transport: StreamableHTTPServerTransport,
    data: string
  ): Promise<void> {
    const message: LoggingMessageNotification = {
      method: 'notifications/message',
      params: { level: 'info', data: data },
    };

    const rpcNotification: JSONRPCNotification = {
      ...message,
      jsonrpc: JSON_RPC,
    };

    await transport.send(rpcNotification);
  }

  /**
   * Split text into chunks for streaming
   */
  private chunkText(text: string, chunkSize: number): string[] {
    const chunks: string[] = [];
    for (let i = 0; i < text.length; i += chunkSize) {
      chunks.push(text.slice(i, i + chunkSize));
    }
    return chunks;
  }

  private createErrorResponse(message: string) {
    return {
      jsonrpc: '2.0',
      error: {
        code: -32000,
        message: message,
      },
      id: randomUUID(),
    };
  }

  private isInitializeRequest(body: any): boolean {
    const isInitial = (data: any) => {
      const result = InitializeRequestSchema.safeParse(data);
      return result.success;
    };
    if (Array.isArray(body)) {
      return body.some(request => isInitial(request));
    }
    return isInitial(body);
  }
}
