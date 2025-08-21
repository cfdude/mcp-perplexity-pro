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
    const storageManager = new StorageManager(config);

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
    } as PerplexityResponse & {
      chat_id: string;
      selected_model: string;
      model_selection_reason: string;
      conversation_length: number;
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
    const storageManager = new StorageManager(config);
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
    const storageManager = new StorageManager(config);
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
    const storageManager = new StorageManager(config);
    const stats = await storageManager.getStorageStats();
    
    return {
      ...stats,
      storage_path: config.storage_path,
    };
  } catch (error) {
    if (error instanceof StorageError) {
      return StorageManager.handleError(error);
    }
    return {
      error: {
        type: 'storage_error',
        message: error instanceof Error ? error.message : 'Unknown error getting storage statistics',
        details: {
          suggestion: 'Check storage configuration and file permissions',
        },
      },
    };
  }
}