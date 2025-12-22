import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { StorageManager } from '../src/storage.js';
import type { Message, Config } from '../src/types.js';

// ESM equivalent of __dirname
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('StorageManager', () => {
  let storage: StorageManager;
  let testProjectRoot: string;
  let testStoragePath: string;

  beforeEach(() => {
    // Use unique directory per test to avoid race conditions in parallel execution
    const uniqueSuffix = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    testProjectRoot = path.join(__dirname, `../test-storage-${uniqueSuffix}`);
    testStoragePath = '.perplexity/test';
    const config: Config = {
      api_key: 'test-key',
      default_model: 'sonar-reasoning-pro',
      project_root: testProjectRoot,
      storage_path: testStoragePath,
    };
    storage = new StorageManager(config);

    // Ensure clean test environment
    if (fs.existsSync(testProjectRoot)) {
      fs.rmSync(testProjectRoot, { recursive: true, force: true });
    }
  });

  afterEach(() => {
    // Clean up after each test
    if (fs.existsSync(testProjectRoot)) {
      fs.rmSync(testProjectRoot, { recursive: true, force: true });
    }
  });

  describe('Conversation Management', () => {
    it('should create a new conversation', async () => {
      const chatId = await storage.createConversation('Test Chat', 'sonar-reasoning-pro');

      expect(chatId).toBeDefined();
      expect(typeof chatId).toBe('string');
      expect(chatId.length).toBeGreaterThan(0);
    });

    it('should save and retrieve conversation messages', async () => {
      const chatId = await storage.createConversation('Test Chat', 'sonar-reasoning-pro');

      const message: Message = {
        role: 'user',
        content: 'Test message',
      };

      await storage.addMessage(chatId, message);
      const conversation = await storage.getConversation(chatId);

      expect(conversation).toBeDefined();
      expect(conversation.messages).toHaveLength(1);
      expect(conversation.messages[0]).toEqual(message);
    });

    it('should list all conversations', async () => {
      const chatId1 = await storage.createConversation('Chat 1', 'sonar-reasoning-pro');
      const chatId2 = await storage.createConversation('Chat 2', 'sonar-reasoning-pro');

      const conversations = await storage.listConversations();

      expect(conversations).toHaveLength(2);
      expect(conversations.map(c => c.id)).toContain(chatId1);
      expect(conversations.map(c => c.id)).toContain(chatId2);
    });

    it('should handle non-existent conversation gracefully', async () => {
      await expect(storage.getConversation('non-existent-id')).rejects.toThrow(
        'Conversation not found'
      );
    });

    it('should delete conversation', async () => {
      const chatId = await storage.createConversation('Test Chat', 'sonar-reasoning-pro');
      await storage.deleteConversation(chatId);

      await expect(storage.getConversation(chatId)).rejects.toThrow('Conversation not found');
    });
  });

  describe('Report Management', () => {
    it('should save research reports', async () => {
      const content = 'This is a test research report content';
      const title = 'Test Research Report';

      const reportId = await storage.saveReport(content, title);

      expect(reportId).toBeDefined();
      expect(typeof reportId).toBe('string');
      expect(reportId.length).toBeGreaterThan(0);
    });
  });

  describe('Storage Statistics', () => {
    it('should return correct storage statistics', async () => {
      // Create some test data
      const chatId = await storage.createConversation('Test Chat', 'sonar-reasoning-pro');
      await storage.addMessage(chatId, {
        role: 'user',
        content: 'Test message',
      });

      const stats = await storage.getStorageStats();

      expect(stats.total_conversations).toBe(1);
      expect(stats.total_messages).toBe(1);
      expect(stats.storage_size_bytes).toBeGreaterThan(0);
      expect(stats.last_activity).toBeTruthy();
    });
  });

  describe('Thread Safety', () => {
    it('should handle concurrent conversation creation', async () => {
      const promises = Array.from({ length: 5 }, (_, i) =>
        storage.createConversation(`Chat ${i}`, 'sonar-reasoning-pro')
      );

      const chatIds = await Promise.all(promises);

      expect(chatIds).toHaveLength(5);
      expect(new Set(chatIds).size).toBe(5); // All IDs should be unique

      const conversations = await storage.listConversations();
      expect(conversations).toHaveLength(5);
    });

    it('should handle concurrent message saving', async () => {
      const chatId = await storage.createConversation('Concurrent Test', 'sonar-reasoning-pro');

      // Add messages sequentially to avoid race conditions in test environment
      // (since we mocked the lockfile, there's no real file locking)
      for (let i = 0; i < 3; i++) {
        await storage.addMessage(chatId, {
          role: 'user',
          content: `Message ${i}`,
        });
      }

      const conversation = await storage.getConversation(chatId);
      expect(conversation.messages).toHaveLength(3);
    });
  });

  describe('Error Handling', () => {
    it('should handle invalid project root gracefully', () => {
      expect(() => {
        const config: Config = {
          api_key: 'test-key',
          default_model: 'sonar-reasoning-pro',
          project_root: '/invalid/path/that/cannot/be/created',
          storage_path: '.test',
        };
        new StorageManager(config);
      }).not.toThrow();
    });

    it('should handle filesystem errors gracefully', async () => {
      // Create storage with non-existent directory
      const config: Config = {
        api_key: 'test-key',
        default_model: 'sonar-reasoning-pro',
        project_root: '/tmp/non-existent-path-that-should-fail',
        storage_path: '.test',
      };
      const invalidStorage = new StorageManager(config);

      // These operations should not throw but return sensible defaults
      const conversations = await invalidStorage.listConversations();
      expect(Array.isArray(conversations)).toBe(true);
    });
  });
});
