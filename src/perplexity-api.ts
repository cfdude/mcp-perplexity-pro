import fetch from 'node-fetch';
import type {
  PerplexityRequest,
  PerplexityResponse,
  AsyncJob,
  ErrorResponse,
  Config,
} from './types.js';
import { suggestFallbackModel } from './models.js';

// Perplexity API endpoints
const PERPLEXITY_BASE_URL = 'https://api.perplexity.ai';
const CHAT_COMPLETIONS_ENDPOINT = '/chat/completions';
const ASYNC_CHAT_COMPLETIONS_ENDPOINT = '/async/chat/completions';

export class PerplexityApiError extends Error {
  constructor(
    message: string,
    public status?: number,
    public response?: any
  ) {
    super(message);
    this.name = 'PerplexityApiError';
  }
}

export class PerplexityApiClient {
  private apiKey: string;
  private baseUrl: string;

  constructor(config: Config) {
    this.apiKey = config.api_key;
    this.baseUrl = PERPLEXITY_BASE_URL;
  }

  /**
   * Makes a request to the Perplexity API with proper error handling
   */
  private async makeRequest<T>(endpoint: string, body: any, method = 'POST'): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;

    try {
      const response = await fetch(url, {
        method,
        headers: {
          Authorization: `Bearer ${this.apiKey}`,
          'Content-Type': 'application/json',
        },
        body: method === 'POST' ? JSON.stringify(body) : null,
      });

      const data: any = await response.json();

      if (!response.ok) {
        throw new PerplexityApiError(
          data.error?.message || `HTTP ${response.status}: ${response.statusText}`,
          response.status,
          data
        );
      }

      return data as T;
    } catch (error) {
      if (error instanceof PerplexityApiError) {
        throw error;
      }

      if (error instanceof Error) {
        throw new PerplexityApiError(`Network error: ${error.message}`);
      }

      throw new PerplexityApiError('Unknown error occurred');
    }
  }

  /**
   * Sends a chat completion request to Perplexity
   */
  async chatCompletion(request: PerplexityRequest): Promise<PerplexityResponse> {
    // Prepare the request body according to Perplexity API format
    const requestBody = {
      model: request.model,
      messages: request.messages,
      ...(request.max_tokens && { max_tokens: request.max_tokens }),
      ...(request.temperature !== undefined && { temperature: request.temperature }),
      ...(request.top_p !== undefined && { top_p: request.top_p }),
      ...(request.search_domain_filter && { search_domain_filter: request.search_domain_filter }),
      ...(request.return_images !== undefined && { return_images: request.return_images }),
      ...(request.return_related_questions !== undefined && {
        return_related_questions: request.return_related_questions,
      }),
      ...(request.search_recency_filter && { search_recency_filter: request.search_recency_filter }),
      ...(request.search_after_date_filter && {
        search_after_date_filter: request.search_after_date_filter,
      }),
      ...(request.search_before_date_filter && {
        search_before_date_filter: request.search_before_date_filter,
      }),
      ...(request.last_updated_after_filter && {
        last_updated_after_filter: request.last_updated_after_filter,
      }),
      ...(request.last_updated_before_filter && {
        last_updated_before_filter: request.last_updated_before_filter,
      }),
      ...(request.top_k !== undefined && { top_k: request.top_k }),
      ...(request.stream !== undefined && { stream: request.stream }),
      ...(request.presence_penalty !== undefined && { presence_penalty: request.presence_penalty }),
      ...(request.frequency_penalty !== undefined && {
        frequency_penalty: request.frequency_penalty,
      }),
      ...(request.response_format && { response_format: request.response_format }),
      ...(request.disable_search !== undefined && { disable_search: request.disable_search }),
      ...(request.enable_search_classifier !== undefined && {
        enable_search_classifier: request.enable_search_classifier,
      }),
      ...(request.web_search_options && { web_search_options: request.web_search_options }),
    };

    return this.makeRequest<PerplexityResponse>(CHAT_COMPLETIONS_ENDPOINT, requestBody);
  }

  /**
   * Creates an async chat completion job
   */
  async createAsyncChatCompletion(request: PerplexityRequest): Promise<AsyncJob> {
    const requestBody = {
      request: {
        model: request.model,
        messages: request.messages,
        ...(request.max_tokens && { max_tokens: request.max_tokens }),
        ...(request.temperature !== undefined && { temperature: request.temperature }),
        ...(request.top_p !== undefined && { top_p: request.top_p }),
        ...(request.search_domain_filter && { search_domain_filter: request.search_domain_filter }),
        ...(request.return_images !== undefined && { return_images: request.return_images }),
        ...(request.return_related_questions !== undefined && {
          return_related_questions: request.return_related_questions,
        }),
        ...(request.search_recency_filter && {
          search_recency_filter: request.search_recency_filter,
        }),
        ...(request.search_after_date_filter && {
          search_after_date_filter: request.search_after_date_filter,
        }),
        ...(request.search_before_date_filter && {
          search_before_date_filter: request.search_before_date_filter,
        }),
        ...(request.last_updated_after_filter && {
          last_updated_after_filter: request.last_updated_after_filter,
        }),
        ...(request.last_updated_before_filter && {
          last_updated_before_filter: request.last_updated_before_filter,
        }),
        ...(request.top_k !== undefined && { top_k: request.top_k }),
        ...(request.stream !== undefined && { stream: request.stream }),
        ...(request.presence_penalty !== undefined && {
          presence_penalty: request.presence_penalty,
        }),
        ...(request.frequency_penalty !== undefined && {
          frequency_penalty: request.frequency_penalty,
        }),
        ...(request.response_format && { response_format: request.response_format }),
        ...(request.disable_search !== undefined && { disable_search: request.disable_search }),
        ...(request.enable_search_classifier !== undefined && {
          enable_search_classifier: request.enable_search_classifier,
        }),
        ...(request.web_search_options && { web_search_options: request.web_search_options }),
      },
    };

    return this.makeRequest<AsyncJob>(ASYNC_CHAT_COMPLETIONS_ENDPOINT, requestBody);
  }

  /**
   * Alias for backward compatibility
   */
  async createAsyncChat(request: PerplexityRequest): Promise<AsyncJob> {
    return this.createAsyncChatCompletion(request);
  }

  /**
   * Lists async chat completion jobs
   */
  async listAsyncJobs(
    limit = 20,
    nextToken?: string
  ): Promise<{ jobs: AsyncJob[]; next_token?: string }> {
    const params = new URLSearchParams();
    params.append('limit', limit.toString());
    if (nextToken) {
      params.append('next_token', encodeURIComponent(nextToken));
    }

    const endpoint = `${ASYNC_CHAT_COMPLETIONS_ENDPOINT}?${params.toString()}`;
    return this.makeRequest(endpoint, null, 'GET');
  }

  /**
   * Gets the status and result of an async job
   */
  async getAsyncJob(jobId: string): Promise<AsyncJob> {
    const endpoint = `${ASYNC_CHAT_COMPLETIONS_ENDPOINT}/${jobId}`;
    return this.makeRequest<AsyncJob>(endpoint, null, 'GET');
  }

  /**
   * Handles API errors and creates structured error responses
   */
  static handleError(error: unknown, context?: { model?: string; query?: string }): ErrorResponse {
    if (error instanceof PerplexityApiError) {
      // Rate limiting
      if (error.status === 429) {
        return {
          error: {
            type: 'rate_limit',
            message: 'Rate limit exceeded',
            details: {
              suggestion: 'Wait before retrying or use async_perplexity for queuing',
              retry_after: error.response?.headers?.['retry-after'] || 60,
              ...(context?.model && {
                fallback_model: suggestFallbackModel(context.model as any, 'rate_limit'),
              }),
            },
          },
        };
      }

      // Invalid model
      if (error.status === 400 && error.message.toLowerCase().includes('model')) {
        return {
          error: {
            type: 'invalid_model',
            message: `Invalid model: ${context?.model || 'unknown'}`,
            details: {
              suggestion:
                'Use a supported model: sonar, sonar-pro, sonar-reasoning, sonar-reasoning-pro, sonar-deep-research',
              fallback_model: 'sonar-reasoning-pro',
            },
          },
        };
      }

      // Authentication error
      if (error.status === 401) {
        return {
          error: {
            type: 'api_error',
            message: 'Authentication failed - check your API key',
            details: {
              suggestion: 'Verify your Perplexity API key is correct and has sufficient credits',
            },
          },
        };
      }

      // Server error
      if (error.status && error.status >= 500) {
        return {
          error: {
            type: 'api_error',
            message: 'Perplexity API server error',
            details: {
              suggestion: 'Try again later or use a different model',
              fallback_model: context?.model
                ? suggestFallbackModel(context.model as any)
                : 'sonar',
            },
          },
        };
      }

      // General API error
      return {
        error: {
          type: 'api_error',
          message: error.message || 'Unknown API error',
          details: {
            suggestion: 'Check your request parameters and try again',
            fallback_model: context?.model
              ? suggestFallbackModel(context.model as any)
              : 'sonar-reasoning-pro',
          },
        },
      };
    }

    // Network or unknown error
    return {
      error: {
        type: 'api_error',
        message: error instanceof Error ? error.message : 'Unknown error occurred',
        details: {
          suggestion: 'Check your internet connection and try again',
        },
      },
    };
  }
}

// Export alias for backward compatibility
export { PerplexityApiClient as PerplexityAPI };