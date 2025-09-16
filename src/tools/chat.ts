import type {
  ChatPerplexityParams,
  ReadChatParams,
  Config,
  PerplexityResponse,
  ErrorResponse,
  ChatMetadata,
  Conversation,
} from '../types.js';
import { PerplexityApiClient } from '../perplexity-api.js';
import { StorageManager, StorageError } from '../storage.js';
import { selectOptimalModel } from '../models.js';

/**
 * Handles the chat_perplexity tool - conversational interface with storage
 */
export async function handleChatPerplexity(
  params: ChatPerplexityParams,
  config: Config
): Promise<
  | (PerplexityResponse & {
      chat_id: string;
      selected_model: string;
      model_selection_reason: string;
      conversation_length: number;
    })
  | ErrorResponse
> {
  try {
    const apiClient = new PerplexityApiClient(config);

    // Detect project and create project-aware config
    const { detectProjectWithSuggestions } = await import('./projects.js');
    const projectName = await detectProjectWithSuggestions(params.project_name, config);

    // Create project-specific storage config with chat subdirectory
    const projectConfig = {
      ...config,
      project_root: config.project_root,
      storage_path: `projects/${projectName}/chat`,
    };

    const storageManager = new StorageManager(projectConfig);

    let conversation: Conversation;
    let chatId: string;
    let isNewChat = false;

    // Handle existing vs new conversation
    if (params.chat_id) {
      // Continue existing conversation
      conversation = await storageManager.getConversation(params.chat_id);
      chatId = params.chat_id;
    } else {
      // Create new conversation
      if (!params.title) {
        return {
          error: {
            type: 'validation_error',
            message: 'Title is required for new conversations',
            details: {
              suggestion: 'Provide a title parameter when starting a new conversation',
            },
          },
        };
      }

      // Select model for the conversation
      const selectedModel = selectOptimalModel(params.message, params.model, config.default_model);

      // Create new conversation with the user's first message
      const userMessage = { role: 'user' as const, content: params.message };
      chatId = await storageManager.createConversation(params.title, selectedModel, userMessage);
      conversation = await storageManager.getConversation(chatId);
      isNewChat = true;
    }

    // Add user message to existing conversation
    if (!isNewChat) {
      const userMessage = { role: 'user' as const, content: params.message };
      await storageManager.addMessage(chatId, userMessage);
      conversation = await storageManager.getConversation(chatId);
    }

    // Select model (use conversation's model or allow override)
    const selectedModel = params.model || conversation.metadata.model;

    // Prepare the API request with conversation history
    const request = {
      model: selectedModel,
      messages: conversation.messages,
      temperature: params.temperature ?? 0.2,
      ...(params.max_tokens && { max_tokens: params.max_tokens }),
    };

    const response = await apiClient.chatCompletion(request);

    // Add assistant's response to conversation
    if (response.choices[0]?.message?.content) {
      const assistantMessage = {
        role: 'assistant' as const,
        content: response.choices[0].message.content,
      };
      await storageManager.addMessage(chatId, assistantMessage);
    }

    // Get updated conversation for final message count
    const updatedConversation = await storageManager.getConversation(chatId);

    // Save conversation report if requested
    let reportSaved = false;
    let reportPath: string | undefined;

    if (params.save_report && response.choices[0]?.message?.content) {
      try {
        // Create a formatted conversation export for potential saving
        // Note: conversationData would be used if save_report was implemented
        // const conversationData = {
        //   chat_id: chatId,
        //   title: updatedConversation.metadata.title,
        //   model: selectedModel,
        //   created_at: updatedConversation.metadata.created_at,
        //   updated_at: updatedConversation.metadata.updated_at,
        //   message_count: updatedConversation.messages.length,
        //   conversation: updatedConversation.messages.map((msg, index) => ({
        //     message_number: index + 1,
        //     role: msg.role,
        //     content: msg.content,
        //     timestamp: 'N/A' // Messages don't have individual timestamps
        //   }))
        // };

        const reportContent =
          `# Chat Export: ${updatedConversation.metadata.title}\n\n` +
          `**Chat ID:** ${chatId}\n` +
          `**Model:** ${selectedModel}\n` +
          `**Created:** ${new Date(updatedConversation.metadata.created_at).toLocaleString()}\n` +
          `**Messages:** ${updatedConversation.messages.length}\n\n` +
          '## Conversation\n\n' +
          updatedConversation.messages
            .map((msg, index) => `### Message ${index + 1} (${msg.role})\n\n${msg.content}\n`)
            .join('\n');

        const reportId = await storageManager.saveReport(
          reportContent,
          `Chat: ${updatedConversation.metadata.title}`
        );
        reportSaved = true;
        reportPath = `projects/${params.project_name || 'default-project'}/chat/reports/${reportId}`;
      } catch (storageError) {
        // Don't fail the entire request if saving fails
        console.warn('Failed to save chat report:', storageError);
      }
    }

    return {
      ...response,
      chat_id: chatId,
      selected_model: selectedModel,
      model_selection_reason: params.model
        ? 'user_specified'
        : isNewChat
          ? 'auto_selected'
          : 'conversation_default',
      conversation_length: updatedConversation.messages.length,
      ...(params.save_report && { report_saved: reportSaved }),
      ...(reportPath && { report_path: reportPath }),
    } as PerplexityResponse & {
      chat_id: string;
      selected_model: string;
      model_selection_reason: string;
      conversation_length: number;
      report_saved?: boolean;
      report_path?: string;
    };
  } catch (error) {
    if (error instanceof StorageError) {
      return StorageManager.handleError(error);
    }
    return PerplexityApiClient.handleError(error, {
      model: params.model || config.default_model,
      query: params.message,
    });
  }
}

/**
 * Handles the list_chats_perplexity tool - lists all conversations
 */
export async function handleListChats(config: Config): Promise<ChatMetadata[] | ErrorResponse> {
  try {
    // Use default project for listing chats
    const { detectProjectWithSuggestions } = await import('./projects.js');
    const projectName = await detectProjectWithSuggestions(undefined, config);

    const projectConfig = {
      ...config,
      storage_path: `projects/${projectName}/chat`,
    };

    const storageManager = new StorageManager(projectConfig);
    return await storageManager.listConversations();
  } catch (error) {
    if (error instanceof StorageError) {
      return StorageManager.handleError(error);
    }
    return {
      error: {
        type: 'storage_error',
        message: error instanceof Error ? error.message : 'Unknown error listing conversations',
        details: {
          suggestion: 'Check storage configuration and file permissions',
        },
      },
    };
  }
}

/**
 * Handles the read_chat_perplexity tool - retrieves conversation history
 */
export async function handleReadChat(
  params: ReadChatParams,
  config: Config
): Promise<Conversation | ErrorResponse> {
  try {
    // Use default project for reading chats
    const { detectProjectWithSuggestions } = await import('./projects.js');
    const projectName = await detectProjectWithSuggestions(undefined, config);

    const projectConfig = {
      ...config,
      storage_path: `projects/${projectName}/chat`,
    };

    const storageManager = new StorageManager(projectConfig);
    return await storageManager.getConversation(params.chat_id);
  } catch (error) {
    if (error instanceof StorageError) {
      return StorageManager.handleError(error);
    }
    return {
      error: {
        type: 'storage_error',
        message: error instanceof Error ? error.message : 'Unknown error reading conversation',
        details: {
          suggestion: 'Check that the conversation ID exists and is accessible',
        },
      },
    };
  }
}

/**
 * Gets storage statistics for the project
 */
export async function handleStorageStats(config: Config): Promise<
  | {
      total_conversations: number;
      total_messages: number;
      storage_size_bytes: number;
      last_activity: string | null;
      storage_path: string;
    }
  | ErrorResponse
> {
  try {
    // Use default project for storage stats
    const { detectProjectWithSuggestions } = await import('./projects.js');
    const projectName = await detectProjectWithSuggestions(undefined, config);

    const projectConfig = {
      ...config,
      storage_path: `projects/${projectName}/chat`,
    };

    const storageManager = new StorageManager(projectConfig);
    const stats = await storageManager.getStorageStats();

    return {
      ...stats,
      storage_path: `projects/${projectName}/chat`,
    };
  } catch (error) {
    if (error instanceof StorageError) {
      return StorageManager.handleError(error);
    }
    return {
      error: {
        type: 'storage_error',
        message:
          error instanceof Error ? error.message : 'Unknown error getting storage statistics',
        details: {
          suggestion: 'Check storage configuration and file permissions',
        },
      },
    };
  }
}
