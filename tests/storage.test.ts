import { describe, it, expect, beforeEach, afterEach } from '@jest/globals';
import fs from 'fs';
import path from 'path';
import { StorageManager } from '../src/storage.js';
import type { ChatMessage, AsyncJobReport } from '../src/types.js';

describe('StorageManager', () => {
  let storage: StorageManager;
  let testProjectRoot: string;
  let testStoragePath: string;

  beforeEach(() => {
    testProjectRoot = path.join(__dirname, '../test-storage');
    testStoragePath = '.perplexity/test';
    storage = new StorageManager(testProjectRoot, testStoragePath);
    
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

  describe('Chat Management', () => {
    it('should create a new chat', async () => {
      const chatId = await storage.createChat('Test Chat');
      
      expect(chatId).toBeDefined();
      expect(typeof chatId).toBe('string');
      expect(chatId.length).toBeGreaterThan(0);
    });

    it('should save and retrieve chat messages', async () => {
      const chatId = await storage.createChat('Test Chat');
      
      const message: ChatMessage = {
        role: 'user',
        content: 'Test message',
        timestamp: new Date().toISOString()
      };

      await storage.saveChatMessage(chatId, message);
      const chat = await storage.getChat(chatId);

      expect(chat).toBeDefined();
      expect(chat!.messages).toHaveLength(1);
      expect(chat!.messages[0]).toEqual(message);
    });

    it('should list all chats', async () => {
      const chatId1 = await storage.createChat('Chat 1');
      const chatId2 = await storage.createChat('Chat 2');

      const chats = await storage.listChats();

      expect(chats).toHaveLength(2);
      expect(chats.map(c => c.id)).toContain(chatId1);
      expect(chats.map(c => c.id)).toContain(chatId2);
    });

    it('should handle non-existent chat gracefully', async () => {
      const chat = await storage.getChat('non-existent-id');
      expect(chat).toBeNull();
    });

    it('should update chat title', async () => {
      const chatId = await storage.createChat('Original Title');
      await storage.updateChatTitle(chatId, 'Updated Title');

      const chat = await storage.getChat(chatId);
      expect(chat?.title).toBe('Updated Title');
    });
  });

  describe('Report Management', () => {
    it('should save and retrieve research reports', async () => {
      const report: AsyncJobReport = {
        id: 'test-report-id',
        query: 'Test research query',
        model: 'sonar-deep-research',
        status: 'completed',
        result: 'Test research result',
        created_at: new Date().toISOString(),
        completed_at: new Date().toISOString()
      };

      await storage.saveReport(report);
      const retrievedReport = await storage.getReport('test-report-id');

      expect(retrievedReport).toEqual(report);
    });

    it('should list all reports', async () => {
      const report1: AsyncJobReport = {
        id: 'report-1',
        query: 'Query 1',
        model: 'sonar-deep-research',
        status: 'completed',
        result: 'Result 1',
        created_at: new Date().toISOString(),
        completed_at: new Date().toISOString()
      };

      const report2: AsyncJobReport = {
        id: 'report-2',
        query: 'Query 2',
        model: 'sonar-deep-research',
        status: 'pending',
        created_at: new Date().toISOString()
      };

      await storage.saveReport(report1);
      await storage.saveReport(report2);

      const reports = await storage.listReports();

      expect(reports).toHaveLength(2);
      expect(reports.map(r => r.id)).toContain('report-1');
      expect(reports.map(r => r.id)).toContain('report-2');
    });

    it('should handle non-existent report gracefully', async () => {
      const report = await storage.getReport('non-existent-id');
      expect(report).toBeNull();
    });
  });

  describe('Storage Statistics', () => {
    it('should return correct storage statistics', async () => {
      // Create some test data
      const chatId = await storage.createChat('Test Chat');
      await storage.saveChatMessage(chatId, {
        role: 'user',
        content: 'Test message',
        timestamp: new Date().toISOString()
      });

      const report: AsyncJobReport = {
        id: 'test-report',
        query: 'Test query',
        model: 'sonar-deep-research',
        status: 'completed',
        result: 'Test result',
        created_at: new Date().toISOString(),
        completed_at: new Date().toISOString()
      };
      await storage.saveReport(report);

      const stats = await storage.getStorageStats();

      expect(stats.totalChats).toBe(1);
      expect(stats.totalReports).toBe(1);
      expect(stats.totalMessages).toBe(1);
      expect(stats.storageSize).toBeGreaterThan(0);
    });
  });

  describe('Thread Safety', () => {
    it('should handle concurrent chat creation', async () => {
      const promises = Array.from({ length: 5 }, (_, i) =>
        storage.createChat(`Chat ${i}`)
      );

      const chatIds = await Promise.all(promises);

      expect(chatIds).toHaveLength(5);
      expect(new Set(chatIds).size).toBe(5); // All IDs should be unique

      const chats = await storage.listChats();
      expect(chats).toHaveLength(5);
    });

    it('should handle concurrent message saving', async () => {
      const chatId = await storage.createChat('Concurrent Test');

      const promises = Array.from({ length: 3 }, (_, i) =>
        storage.saveChatMessage(chatId, {
          role: 'user',
          content: `Message ${i}`,
          timestamp: new Date().toISOString()
        })
      );

      await Promise.all(promises);

      const chat = await storage.getChat(chatId);
      expect(chat?.messages).toHaveLength(3);
    });
  });

  describe('Error Handling', () => {
    it('should handle invalid project root gracefully', () => {
      expect(() => {
        new StorageManager('/invalid/path/that/cannot/be/created', '.test');
      }).not.toThrow();
    });

    it('should handle filesystem errors gracefully', async () => {
      // Create storage with read-only directory (simulated)
      const invalidStorage = new StorageManager('/root', '.test');
      
      // These operations should not throw but return sensible defaults
      const chats = await invalidStorage.listChats();
      expect(Array.isArray(chats)).toBe(true);
    });
  });
});