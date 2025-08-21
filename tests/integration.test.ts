import { describe, it, expect, beforeEach, afterEach, jest } from '@jest/globals';
import fs from 'fs';
import path from 'path';

// Mock node-fetch before any imports that use it
const mockFetch = jest.fn() as jest.MockedFunction<any>;
jest.unstable_mockModule('node-fetch', () => ({
  default: mockFetch
}));

// Dynamic import after mocking
const { handleAskPerplexity } = await import('../src/tools/query.js');

describe('Integration Tests', () => {
  let testProjectRoot: string;
  let testConfig: any;

  beforeEach(() => {
    testProjectRoot = path.join(process.cwd(), 'test-integration');
    testConfig = {
      api_key: 'test-api-key',
      default_model: 'sonar-reasoning-pro',
      project_root: testProjectRoot,
      storage_path: '.perplexity/test',
      session_id: 'test-session'
    };

    // Clean up test directory
    if (fs.existsSync(testProjectRoot)) {
      fs.rmSync(testProjectRoot, { recursive: true, force: true });
    }
    fs.mkdirSync(testProjectRoot, { recursive: true });

    jest.clearAllMocks();
    mockFetch.mockClear();
  });

  afterEach(() => {
    if (fs.existsSync(testProjectRoot)) {
      fs.rmSync(testProjectRoot, { recursive: true, force: true });
    }
  });

  describe('Query Tool Integration', () => {
    it('should handle ask_perplexity request end-to-end', async () => {
      const mockResponse = {
        id: 'test-id',
        object: 'chat.completion',
        created: Date.now(),
        model: 'sonar-reasoning-pro',
        choices: [{
          message: {
            role: 'assistant',
            content: 'This is a test response from Perplexity AI.'
          },
          finish_reason: 'stop',
          index: 0
        }],
        usage: {
          prompt_tokens: 10,
          completion_tokens: 12,
          total_tokens: 22
        }
      };

      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockResponse,
        text: async () => JSON.stringify(mockResponse),
        blob: async () => new Blob(),
        arrayBuffer: async () => new ArrayBuffer(0),
        formData: async () => new FormData(),
        bytes: async () => new Uint8Array(),
        clone: jest.fn(function(this: any) { return this; }),
        body: null,
        bodyUsed: false,
        redirected: false,
        type: 'basic',
        url: ''
      } as Response);

      const result = await handleAskPerplexity({
        query: 'What is artificial intelligence?',
        model: 'sonar-reasoning-pro'
      }, testConfig);

      expect(result.content[0].type).toBe('text');
      expect(result.content[0].text).toContain('This is a test response from Perplexity AI.');
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.perplexity.ai/chat/completions',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            'Authorization': 'Bearer test-api-key'
          })
        })
      );
    });
  });
});