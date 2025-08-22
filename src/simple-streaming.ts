import type { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { LoggingMessageNotification, JSONRPCNotification } from '@modelcontextprotocol/sdk/types.js';

/**
 * Simple streaming helper that sends LoggingMessageNotifications via STDIO
 * This should work with Claude Code without requiring HTTP/SSE or OAuth
 */
export class SimpleStreaming {
  constructor(private server: Server) {}

  /**
   * Send a streaming message to Claude Code
   */
  async sendMessage(message: string): Promise<void> {
    try {
      const notification: LoggingMessageNotification = {
        method: 'notifications/message',
        params: {
          level: 'info',
          data: message,
        },
      };

      const rpcNotification: JSONRPCNotification = {
        ...notification,
        jsonrpc: '2.0',
      };

      // Send the notification via the server's transport
      await this.server.notification(rpcNotification);
    } catch (error) {
      console.error('Error sending streaming message:', error);
    }
  }

  /**
   * Stream content in chunks with delays for a typewriter effect
   */
  async streamContent(content: string, chunkSize: number = 100, delayMs: number = 50): Promise<void> {
    const chunks = this.chunkText(content, chunkSize);
    
    for (const chunk of chunks) {
      await this.sendMessage(chunk);
      if (delayMs > 0) {
        await new Promise(resolve => setTimeout(resolve, delayMs));
      }
    }
  }

  /**
   * Wrap a tool handler with streaming capabilities
   */
  async wrapWithStreaming<T>(
    toolName: string,
    handler: () => Promise<T>,
    startMessage?: string
  ): Promise<T> {
    try {
      // Send start message
      await this.sendMessage(startMessage || `🚀 Starting ${toolName}...`);
      
      // Execute the handler
      const result = await handler();
      
      // Send completion message
      await this.sendMessage('✅ Complete!');
      
      return result;
    } catch (error) {
      // Send error message
      await this.sendMessage(`❌ Error: ${error instanceof Error ? error.message : String(error)}`);
      throw error;
    }
  }

  /**
   * Split text into chunks
   */
  private chunkText(text: string, chunkSize: number): string[] {
    const chunks: string[] = [];
    for (let i = 0; i < text.length; i += chunkSize) {
      chunks.push(text.slice(i, i + chunkSize));
    }
    return chunks;
  }
}