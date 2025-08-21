import { describe, it, expect, beforeEach, jest } from '@jest/globals';
import { PerplexityAPI } from '../src/perplexity-api.js';
import type { ChatCompletionRequest, AsyncChatRequest } from '../src/types.js';

// Mock fetch globally
global.fetch = jest.fn() as jest.MockedFunction<typeof fetch>;

describe('PerplexityAPI', () => {
  let api: PerplexityAPI;
  const mockApiKey = 'test-api-key';

  beforeEach(() => {
    api = new PerplexityAPI(mockApiKey);
    jest.clearAllMocks();
  });

  describe('Chat Completions', () => {
    it('should make successful chat completion request', async () => {
      const mockResponse = {
        id: 'test-id',
        object: 'chat.completion',
        created: Date.now(),
        model: 'sonar-reasoning-pro',
        choices: [{
          message: {
            role: 'assistant',
            content: 'Test response'
          },
          finish_reason: 'stop',
          index: 0
        }],
        usage: {
          prompt_tokens: 10,
          completion_tokens: 5,
          total_tokens: 15
        }
      };

      (fetch as jest.MockedFunction<typeof fetch>).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockResponse
      } as Response);

      const request: ChatCompletionRequest = {
        model: 'sonar-reasoning-pro',
        messages: [{ role: 'user', content: 'Test question' }]
      };

      const result = await api.chatCompletion(request);

      expect(result).toEqual(mockResponse);
      expect(fetch).toHaveBeenCalledWith(
        'https://api.perplexity.ai/chat/completions',
        expect.objectContaining({
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${mockApiKey}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(request)
        })
      );
    });

    it('should handle API errors gracefully', async () => {
      const errorResponse = {
        error: {
          type: 'invalid_request_error',
          message: 'Invalid model specified'
        }
      };

      (fetch as jest.MockedFunction<typeof fetch>).mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: async () => errorResponse
      } as Response);

      const request: ChatCompletionRequest = {
        model: 'invalid-model' as any,
        messages: [{ role: 'user', content: 'Test question' }]
      };

      await expect(api.chatCompletion(request)).rejects.toThrow(
        'Perplexity API error (400): Invalid model specified'
      );
    });

    it('should handle network errors', async () => {
      (fetch as jest.MockedFunction<typeof fetch>).mockRejectedValueOnce(
        new Error('Network error')
      );

      const request: ChatCompletionRequest = {
        model: 'sonar-reasoning-pro',
        messages: [{ role: 'user', content: 'Test question' }]
      };

      await expect(api.chatCompletion(request)).rejects.toThrow(
        'Network error while calling Perplexity API: Network error'
      );
    });

    it('should handle malformed JSON responses', async () => {
      (fetch as jest.MockedFunction<typeof fetch>).mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => { throw new Error('Invalid JSON'); }
      } as Response);

      const request: ChatCompletionRequest = {
        model: 'sonar-reasoning-pro',
        messages: [{ role: 'user', content: 'Test question' }]
      };

      await expect(api.chatCompletion(request)).rejects.toThrow(
        'Perplexity API error (500): Unknown error occurred'
      );
    });
  });

  describe('Async Chat', () => {
    it('should create async chat job successfully', async () => {
      const mockResponse = {
        id: 'async-job-123',
        object: 'async_chat',
        status: 'pending',
        model: 'sonar-deep-research',
        created_at: new Date().toISOString()
      };

      (fetch as jest.MockedFunction<typeof fetch>).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockResponse
      } as Response);

      const request: AsyncChatRequest = {
        model: 'sonar-deep-research',
        messages: [{ role: 'user', content: 'Research question' }]
      };

      const result = await api.createAsyncChat(request);

      expect(result).toEqual(mockResponse);
      expect(fetch).toHaveBeenCalledWith(
        'https://api.perplexity.ai/chat/async',
        expect.objectContaining({
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${mockApiKey}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(request)
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
        choices: [{
          message: {
            role: 'assistant',
            content: 'Research result'
          },
          finish_reason: 'stop',
          index: 0
        }],
        usage: {
          prompt_tokens: 100,
          completion_tokens: 500,
          total_tokens: 600
        }
      };

      (fetch as jest.MockedFunction<typeof fetch>).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => mockResponse
      } as Response);

      const result = await api.getAsyncChat('async-job-123');

      expect(result).toEqual(mockResponse);
      expect(fetch).toHaveBeenCalledWith(
        'https://api.perplexity.ai/chat/async/async-job-123',
        expect.objectContaining({
          method: 'GET',
          headers: {
            'Authorization': `Bearer ${mockApiKey}`,
            'Content-Type': 'application/json'
          }
        })
      );
    });

    it('should handle async job not found error', async () => {
      const errorResponse = {
        error: {
          type: 'not_found_error',
          message: 'Async job not found'
        }
      };

      (fetch as jest.MockedFunction<typeof fetch>).mockResolvedValueOnce({
        ok: false,
        status: 404,
        json: async () => errorResponse
      } as Response);

      await expect(api.getAsyncChat('non-existent-job')).rejects.toThrow(
        'Perplexity API error (404): Async job not found'
      );
    });
  });

  describe('Request Validation', () => {
    it('should include proper headers', async () => {
      (fetch as jest.MockedFunction<typeof fetch>).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ choices: [] })
      } as Response);

      await api.chatCompletion({
        model: 'sonar-reasoning-pro',
        messages: [{ role: 'user', content: 'test' }]
      });

      expect(fetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: expect.objectContaining({
            'Authorization': `Bearer ${mockApiKey}`,
            'Content-Type': 'application/json'
          })
        })
      );
    });

    it('should properly serialize request body', async () => {
      (fetch as jest.MockedFunction<typeof fetch>).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ choices: [] })
      } as Response);

      const request: ChatCompletionRequest = {
        model: 'sonar-reasoning-pro',
        messages: [{ role: 'user', content: 'test' }],
        temperature: 0.7,
        max_tokens: 100
      };

      await api.chatCompletion(request);

      expect(fetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          body: JSON.stringify(request)
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
          code: 'rate_limit_exceeded'
        }
      };

      (fetch as jest.MockedFunction<typeof fetch>).mockResolvedValueOnce({
        ok: false,
        status: 429,
        json: async () => errorResponse
      } as Response);

      try {
        await api.chatCompletion({
          model: 'sonar-reasoning-pro',
          messages: [{ role: 'user', content: 'test' }]
        });
      } catch (error) {
        expect(error).toBeInstanceOf(Error);
        expect((error as Error).message).toContain('429');
        expect((error as Error).message).toContain('Rate limit exceeded');
      }
    });

    it('should handle unexpected error formats', async () => {
      (fetch as jest.MockedFunction<typeof fetch>).mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => ({ unexpected: 'format' })
      } as Response);

      try {
        await api.chatCompletion({
          model: 'sonar-reasoning-pro',
          messages: [{ role: 'user', content: 'test' }]
        });
      } catch (error) {
        expect(error).toBeInstanceOf(Error);
        expect((error as Error).message).toContain('500');
        expect((error as Error).message).toContain('Unknown error occurred');
      }
    });
  });
});