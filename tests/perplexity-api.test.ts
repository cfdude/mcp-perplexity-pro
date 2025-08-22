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

      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        headers: new Headers(),
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

      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: async () => errorResponse,
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

      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockResponse,
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
      const mockResponse = {
        id: 'async-job-123',
        object: 'async_chat',
        status: 'completed',
        model: 'sonar-deep-research',
        created_at: new Date().toISOString(),
        completed_at: new Date().toISOString(),
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

      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockResponse,
      } as Response);

      const result = await api.getAsyncJob('async-job-123');

      expect(result).toEqual(mockResponse);
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.perplexity.ai/async/chat/completions/async-job-123',
        expect.objectContaining({
          method: 'GET',
          headers: {
            Authorization: `Bearer ${mockConfig.api_key}`,
            'Content-Type': 'application/json',
          },
        })
      );
    });

    it('should handle async job not found error', async () => {
      const errorResponse = {
        error: {
          type: 'not_found_error',
          message: 'Async job not found',
        },
      };

      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: async () => errorResponse,
      } as Response);

      await expect(api.getAsyncJob('non-existent-job')).rejects.toThrow('Async job not found');
    });
  });

  describe('Request Validation', () => {
    it('should include proper headers', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ choices: [] }),
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
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ choices: [] }),
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

      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 429,
        json: async () => errorResponse,
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
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => ({ unexpected: 'format' }),
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
