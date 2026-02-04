import { describe, it, expect, beforeEach, vi } from 'vitest';

// Mock node-fetch with Vitest
const mockFetch = vi.fn();
vi.mock('node-fetch', () => ({
  default: mockFetch,
}));

// Dynamic import after mocking
const { PerplexityAPI } = await import('../src/perplexity-api.js');
import type { PerplexityRequest } from '../src/types.js';

describe('PerplexityAPI', () => {
  let api: InstanceType<typeof PerplexityAPI>;
  const mockConfig = {
    api_key: 'test-api-key',
    default_model: 'sonar-reasoning-pro' as const,
    project_root: '/test',
    storage_path: '.perplexity',
  };

  beforeEach(() => {
    api = new PerplexityAPI(mockConfig);
    vi.clearAllMocks();
    mockFetch.mockClear();
  });

  describe('Chat Completions', () => {
    it('should make successful chat completion request', async () => {
      const mockResponse = {
        id: 'test-id',
        object: 'chat.completion',
        created: Date.now(),
        model: 'sonar-reasoning-pro',
        choices: [
          {
            message: {
              role: 'assistant',
              content: 'Test response',
            },
            finish_reason: 'stop',
            index: 0,
          },
        ],
        usage: {
          prompt_tokens: 10,
          completion_tokens: 5,
          total_tokens: 15,
        },
      };

      const mockHeaders = new Headers();
      mockHeaders.set('content-type', 'application/json');

      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        headers: mockHeaders,
        json: async () => mockResponse,
        text: async () => JSON.stringify(mockResponse),
        blob: async () => new Blob(),
        arrayBuffer: async () => new ArrayBuffer(0),
        formData: async () => new FormData(),
        bytes: async () => new Uint8Array(),
        clone: () => ({}) as Response,
        body: null,
        bodyUsed: false,
        redirected: false,
        type: 'basic',
        url: '',
      } as Response);

      const request: PerplexityRequest = {
        model: 'sonar-reasoning-pro',
        messages: [{ role: 'user', content: 'Test question' }],
      };

      const result = await api.chatCompletion(request);

      expect(result).toEqual(mockResponse);
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.perplexity.ai/chat/completions',
        expect.objectContaining({
          method: 'POST',
          headers: {
            Authorization: `Bearer ${mockConfig.api_key}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(request),
        })
      );
    });

    it('should handle API errors gracefully', async () => {
      const errorResponse = {
        error: {
          type: 'invalid_request_error',
          message: 'Invalid model specified',
        },
      };

      const errorHeaders = new Headers();
      errorHeaders.set('content-type', 'application/json');

      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 400,
        headers: errorHeaders,
        json: async () => errorResponse,
        text: async () => JSON.stringify(errorResponse),
      } as Response);

      const request: PerplexityRequest = {
        model: 'invalid-model' as any,
        messages: [{ role: 'user', content: 'Test question' }],
      };

      await expect(api.chatCompletion(request)).rejects.toThrow('Invalid model specified');
    });

    it('should handle network errors', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      const request: PerplexityRequest = {
        model: 'sonar-reasoning-pro',
        messages: [{ role: 'user', content: 'Test question' }],
      };

      await expect(api.chatCompletion(request)).rejects.toThrow('Network error: Network error');
    });

    it('should handle malformed JSON responses', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => {
          throw new Error('Invalid JSON');
        },
        headers: new Headers(),
        redirected: false,
        statusText: 'Internal Server Error',
        type: 'basic' as ResponseType,
        url: 'https://api.perplexity.ai/chat/completions',
        clone: vi.fn(),
        body: null,
        bodyUsed: false,
        arrayBuffer: vi.fn(),
        blob: vi.fn(),
        formData: vi.fn(),
        text: vi.fn(),
        bytes: vi.fn(),
      } as Response);

      const request: PerplexityRequest = {
        model: 'sonar-reasoning-pro',
        messages: [{ role: 'user', content: 'Test question' }],
      };

      await expect(api.chatCompletion(request)).rejects.toThrow();
    });
  });

  describe('Async Chat', () => {
    it('should create async chat job successfully', async () => {
      const mockResponse = {
        id: 'async-job-123',
        object: 'async_chat',
        status: 'pending',
        model: 'sonar-deep-research',
        created_at: new Date().toISOString(),
      };

      const asyncHeaders = new Headers();
      asyncHeaders.set('content-type', 'application/json');

      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: asyncHeaders,
        json: async () => mockResponse,
        text: async () => JSON.stringify(mockResponse),
      } as Response);

      const request: PerplexityRequest = {
        model: 'sonar-deep-research',
        messages: [{ role: 'user', content: 'Research question' }],
      };

      const result = await api.createAsyncChat(request);

      expect(result).toEqual(mockResponse);
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.perplexity.ai/async/chat/completions',
        expect.objectContaining({
          method: 'POST',
          headers: {
            Authorization: `Bearer ${mockConfig.api_key}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ request }),
        })
      );
    });

    it('should get async job status successfully', async () => {
      const createdAt = new Date().toISOString();
      const completedAt = new Date().toISOString();

      // Mock LIST response (called first to check status)
      const mockListResponse = {
        requests: [
          {
            id: 'async-job-123',
            status: 'COMPLETED',
            model: 'sonar-deep-research',
            created_at: createdAt,
            completed_at: completedAt,
          },
        ],
      };

      // Mock GET response (called second for full details)
      const mockGetResponse = {
        id: 'async-job-123',
        object: 'async_chat',
        status: 'IN_PROGRESS', // Note: GET returns stale status (Perplexity API bug)
        model: 'sonar-deep-research',
        created_at: createdAt,
        completed_at: completedAt,
        choices: [
          {
            message: {
              role: 'assistant',
              content: 'Research result',
            },
            finish_reason: 'stop',
            index: 0,
          },
        ],
        usage: {
          prompt_tokens: 100,
          completion_tokens: 500,
          total_tokens: 600,
        },
      };

      const asyncJobHeaders = new Headers();
      asyncJobHeaders.set('content-type', 'application/json');

      // First call: LIST endpoint
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: asyncJobHeaders,
        json: async () => mockListResponse,
        text: async () => JSON.stringify(mockListResponse),
      } as Response);

      // Second call: GET endpoint (for full details since LIST showed COMPLETED)
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: asyncJobHeaders,
        json: async () => mockGetResponse,
        text: async () => JSON.stringify(mockGetResponse),
      } as Response);

      const result = await api.getAsyncJob('async-job-123');

      // Result should use COMPLETED status from LIST, but content from GET
      expect(result.id).toBe('async-job-123');
      expect(result.status).toBe('COMPLETED'); // From LIST, not the stale GET status
      expect(result.choices).toBeDefined();
      expect(result.choices![0].message.content).toBe('Research result');

      // Verify LIST was called first
      expect(mockFetch).toHaveBeenNthCalledWith(
        1,
        'https://api.perplexity.ai/async/chat/completions?limit=10',
        expect.objectContaining({
          method: 'GET',
        })
      );

      // Verify GET was called second for full details
      expect(mockFetch).toHaveBeenNthCalledWith(
        2,
        'https://api.perplexity.ai/async/chat/completions/async-job-123',
        expect.objectContaining({
          method: 'GET',
        })
      );
    });

    it('should handle async job not found error', async () => {
      // Mock LIST response (job not in list)
      const mockListResponse = {
        requests: [], // Empty - job not found in list
      };

      const errorResponse = {
        error: {
          type: 'not_found_error',
          message: 'Async job not found',
        },
      };

      const headers = new Headers();
      headers.set('content-type', 'application/json');

      // First call: LIST endpoint (returns empty)
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: headers,
        json: async () => mockListResponse,
        text: async () => JSON.stringify(mockListResponse),
      } as Response);

      // Second call: GET endpoint (fallback since job not in LIST)
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 404,
        headers: headers,
        json: async () => errorResponse,
        text: async () => JSON.stringify(errorResponse),
      } as Response);

      await expect(api.getAsyncJob('non-existent-job')).rejects.toThrow('Async job not found');
    });
  });

  describe('Request Validation', () => {
    it('should include proper headers', async () => {
      const validationHeaders1 = new Headers();
      validationHeaders1.set('content-type', 'application/json');

      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: validationHeaders1,
        json: async () => ({ choices: [] }),
        text: async () => JSON.stringify({ choices: [] }),
      } as Response);

      await api.chatCompletion({
        model: 'sonar-reasoning-pro',
        messages: [{ role: 'user', content: 'test' }],
      });

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: `Bearer ${mockConfig.api_key}`,
            'Content-Type': 'application/json',
          }),
        })
      );
    });

    it('should properly serialize request body', async () => {
      const validationHeaders2 = new Headers();
      validationHeaders2.set('content-type', 'application/json');

      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: validationHeaders2,
        json: async () => ({ choices: [] }),
        text: async () => JSON.stringify({ choices: [] }),
      } as Response);

      const request: PerplexityRequest = {
        model: 'sonar-reasoning-pro',
        messages: [{ role: 'user', content: 'test' }],
        temperature: 0.7,
        max_tokens: 100,
      };

      await api.chatCompletion(request);

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          body: expect.stringContaining('"model":"sonar-reasoning-pro"'),
        })
      );
    });
  });

  describe('Error Formatting', () => {
    it('should format API errors with details', async () => {
      const errorResponse = {
        error: {
          type: 'rate_limit_error',
          message: 'Rate limit exceeded',
          code: 'rate_limit_exceeded',
        },
      };

      const rateLimitHeaders = new Headers();
      rateLimitHeaders.set('content-type', 'application/json');

      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 429,
        headers: rateLimitHeaders,
        json: async () => errorResponse,
        text: async () => JSON.stringify(errorResponse),
      } as Response);

      try {
        await api.chatCompletion({
          model: 'sonar-reasoning-pro',
          messages: [{ role: 'user', content: 'test' }],
        });
      } catch (error) {
        expect(error).toBeInstanceOf(Error);
        expect((error as Error).message).toContain('Rate limit exceeded');
      }
    });

    it('should handle unexpected error formats', async () => {
      const unexpectedHeaders = new Headers();
      unexpectedHeaders.set('content-type', 'application/json');

      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        headers: unexpectedHeaders,
        json: async () => ({ unexpected: 'format' }),
        text: async () => JSON.stringify({ unexpected: 'format' }),
      } as Response);

      try {
        await api.chatCompletion({
          model: 'sonar-reasoning-pro',
          messages: [{ role: 'user', content: 'test' }],
        });
      } catch (error) {
        expect(error).toBeInstanceOf(Error);
        expect((error as Error).message).toBeTruthy();
      }
    });
  });
});
