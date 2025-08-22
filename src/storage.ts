import { promises as fs } from 'fs';
import path from 'path';
import { v4 as uuidv4 } from 'uuid';
import lockfile from 'proper-lockfile';
import type {
  Config,
  Conversation,
  ChatMetadata,
  Message,
  PerplexityModel,
  ErrorResponse,
} from './types.js';

export class StorageError extends Error {
  constructor(
    message: string,
    public code?: string
  ) {
    super(message);
    this.name = 'StorageError';
  }
}

export class StorageManager {
  private projectRoot: string;
  private storagePath: string;
  private sessionId?: string;

  constructor(config: Config) {
    this.projectRoot = config.project_root;
    this.storagePath = path.join(config.project_root, config.storage_path);
    if (config.session_id) {
      this.sessionId = config.session_id;
    }
  }

  /**
   * Ensures the storage directory exists
   */
  private async ensureStorageDirectory(): Promise<void> {
    try {
      await fs.mkdir(this.storagePath, { recursive: true });
    } catch (error) {
      throw new StorageError(
        `Failed to create storage directory: ${this.storagePath}`,
        'STORAGE_INIT_ERROR'
      );
    }
  }

  /**
   * Gets the full path for a conversation file
   */
  private getConversationPath(chatId: string): string {
    // Include session ID if provided for multi-session support
    const filename = this.sessionId ? `${this.sessionId}_${chatId}.json` : `${chatId}.json`;
    return path.join(this.storagePath, filename);
  }

  /**
   * Gets the path for a research report
   */
  private getReportPath(reportId: string): string {
    const filename = this.sessionId
      ? `${this.sessionId}_report_${reportId}.md`
      : `report_${reportId}.md`;
    return path.join(this.storagePath, filename);
  }

  /**
   * Executes a function with file locking for thread safety
   */
  private async withLock<T>(filePath: string, operation: () => Promise<T>): Promise<T> {
    const lockPath = `${filePath}.lock`;

    try {
      // Ensure directory exists for both the file and lock
      const fileDir = path.dirname(filePath);
      await fs.mkdir(fileDir, { recursive: true });

      // Ensure the target file exists (create empty file if it doesn't exist)
      // This is needed for proper-lockfile to work correctly
      try {
        await fs.access(filePath);
      } catch {
        // File doesn't exist, create empty file
        await fs.writeFile(filePath, '', 'utf-8');
      }

      // Acquire lock with timeout
      await lockfile.lock(filePath, {
        stale: 10000, // 10 seconds
        retries: 3,
      });

      try {
        return await operation();
      } finally {
        // Always release the lock
        await lockfile.unlock(filePath);
      }
    } catch (error) {
      if (error instanceof Error && error.message.includes('EEXIST')) {
        throw new StorageError(
          'Storage operation timed out - another process may be accessing the file',
          'LOCK_TIMEOUT'
        );
      }
      throw error;
    }
  }

  /**
   * Creates a new conversation
   */
  async createConversation(
    title: string,
    model: PerplexityModel,
    initialMessage?: Message
  ): Promise<string> {
    await this.ensureStorageDirectory();

    const chatId = uuidv4();
    const now = new Date().toISOString();

    const conversation: Conversation = {
      metadata: {
        id: chatId,
        title,
        created_at: now,
        updated_at: now,
        message_count: initialMessage ? 1 : 0,
        model,
      },
      messages: initialMessage ? [initialMessage] : [],
    };

    const filePath = this.getConversationPath(chatId);

    await this.withLock(filePath, async () => {
      await fs.writeFile(filePath, JSON.stringify(conversation, null, 2), 'utf-8');
    });

    return chatId;
  }

  /**
   * Adds a message to an existing conversation
   */
  async addMessage(chatId: string, message: Message): Promise<void> {
    const filePath = this.getConversationPath(chatId);

    await this.withLock(filePath, async () => {
      try {
        const data = await fs.readFile(filePath, 'utf-8');
        const conversation: Conversation = JSON.parse(data);

        conversation.messages.push(message);
        conversation.metadata.updated_at = new Date().toISOString();
        conversation.metadata.message_count = conversation.messages.length;

        await fs.writeFile(filePath, JSON.stringify(conversation, null, 2), 'utf-8');
      } catch (error) {
        if (error instanceof Error && error.message.includes('ENOENT')) {
          throw new StorageError(`Conversation not found: ${chatId}`, 'CONVERSATION_NOT_FOUND');
        }
        throw new StorageError(`Failed to add message to conversation: ${chatId}`, 'WRITE_ERROR');
      }
    });
  }

  /**
   * Retrieves a conversation by ID
   */
  async getConversation(chatId: string): Promise<Conversation> {
    const filePath = this.getConversationPath(chatId);

    try {
      const data = await fs.readFile(filePath, 'utf-8');
      return JSON.parse(data) as Conversation;
    } catch (error) {
      if (error instanceof Error && error.message.includes('ENOENT')) {
        throw new StorageError(`Conversation not found: ${chatId}`, 'CONVERSATION_NOT_FOUND');
      }
      throw new StorageError(`Failed to read conversation: ${chatId}`, 'READ_ERROR');
    }
  }

  /**
   * Lists all conversations in the current project
   */
  async listConversations(): Promise<ChatMetadata[]> {
    await this.ensureStorageDirectory();

    try {
      const files = await fs.readdir(this.storagePath);
      const conversations: ChatMetadata[] = [];

      // Filter for conversation files (not reports)
      const conversationFiles = files.filter(file => {
        if (this.sessionId) {
          return (
            file.startsWith(`${this.sessionId}_`) &&
            file.endsWith('.json') &&
            !file.includes('report_')
          );
        }
        return file.endsWith('.json') && !file.includes('report_');
      });

      // Read metadata from each conversation
      for (const file of conversationFiles) {
        try {
          const filePath = path.join(this.storagePath, file);
          const data = await fs.readFile(filePath, 'utf-8');
          const conversation: Conversation = JSON.parse(data);
          conversations.push(conversation.metadata);
        } catch (error) {
          // Skip corrupted files but don't fail the entire operation
          console.warn(`Warning: Could not read conversation file ${file}:`, error);
        }
      }

      // Sort by updated_at descending (most recent first)
      return conversations.sort(
        (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      );
    } catch (error) {
      throw new StorageError('Failed to list conversations', 'LIST_ERROR');
    }
  }

  /**
   * Deletes a conversation
   */
  async deleteConversation(chatId: string): Promise<void> {
    const filePath = this.getConversationPath(chatId);

    try {
      await fs.unlink(filePath);
    } catch (error) {
      if (error instanceof Error && error.message.includes('ENOENT')) {
        throw new StorageError(`Conversation not found: ${chatId}`, 'CONVERSATION_NOT_FOUND');
      }
      throw new StorageError(`Failed to delete conversation: ${chatId}`, 'DELETE_ERROR');
    }
  }

  /**
   * Saves a research report to the project directory
   */
  async saveReport(content: string, title: string): Promise<string> {
    await this.ensureStorageDirectory();

    const reportId = uuidv4();
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const filename = `${timestamp}_${title.replace(/[^a-zA-Z0-9]/g, '_')}.md`;
    const reportPath = path.join(this.storagePath, filename);

    const reportContent = `# ${title}

**Generated:** ${new Date().toLocaleString()}  
**Report ID:** ${reportId}

---

${content}
`;

    try {
      await fs.writeFile(reportPath, reportContent, 'utf-8');
      return reportId;
    } catch (error) {
      throw new StorageError('Failed to save research report', 'SAVE_REPORT_ERROR');
    }
  }

  /**
   * Gets storage statistics for the current project
   */
  async getStorageStats(): Promise<{
    total_conversations: number;
    total_messages: number;
    storage_size_bytes: number;
    last_activity: string | null;
  }> {
    await this.ensureStorageDirectory();

    try {
      const conversations = await this.listConversations();
      let totalMessages = 0;
      let storageSize = 0;
      let lastActivity: string | null = null;

      // Calculate total messages and find last activity
      for (const conv of conversations) {
        totalMessages += conv.message_count;
        if (!lastActivity || new Date(conv.updated_at) > new Date(lastActivity)) {
          lastActivity = conv.updated_at;
        }
      }

      // Calculate storage size
      const files = await fs.readdir(this.storagePath);
      for (const file of files) {
        try {
          const filePath = path.join(this.storagePath, file);
          const stats = await fs.stat(filePath);
          storageSize += stats.size;
        } catch (error) {
          // Skip files we can't access
        }
      }

      return {
        total_conversations: conversations.length,
        total_messages: totalMessages,
        storage_size_bytes: storageSize,
        last_activity: lastActivity,
      };
    } catch (error) {
      throw new StorageError('Failed to get storage statistics', 'STATS_ERROR');
    }
  }

  /**
   * Handles storage errors and creates structured error responses
   */
  static handleError(error: unknown): ErrorResponse {
    if (error instanceof StorageError) {
      switch (error.code) {
        case 'CONVERSATION_NOT_FOUND':
          return {
            error: {
              type: 'storage_error',
              message: error.message,
              details: {
                suggestion:
                  'Check the conversation ID and try again, or list conversations to see available IDs',
              },
            },
          };

        case 'LOCK_TIMEOUT':
          return {
            error: {
              type: 'storage_error',
              message: error.message,
              details: {
                suggestion: 'Try again in a moment - another operation may be in progress',
              },
            },
          };

        case 'STORAGE_INIT_ERROR':
          return {
            error: {
              type: 'storage_error',
              message: error.message,
              details: {
                suggestion: 'Check that the project_root path exists and is writable',
              },
            },
          };

        default:
          return {
            error: {
              type: 'storage_error',
              message: error.message,
              details: {
                suggestion: 'Check file permissions and available disk space',
              },
            },
          };
      }
    }

    return {
      error: {
        type: 'storage_error',
        message: error instanceof Error ? error.message : 'Unknown storage error',
        details: {
          suggestion: 'Check the storage path configuration and file permissions',
        },
      },
    };
  }
}
