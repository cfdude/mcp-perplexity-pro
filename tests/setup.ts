import { jest } from '@jest/globals';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

// ESM equivalent of __dirname
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Setup test environment
beforeAll(() => {
  // Create test storage directory
  const testStorageDir = path.join(__dirname, '../test-storage');
  if (!fs.existsSync(testStorageDir)) {
    fs.mkdirSync(testStorageDir, { recursive: true });
  }
});

afterAll(() => {
  // Clean up test storage directory
  const testStorageDir = path.join(__dirname, '../test-storage');
  if (fs.existsSync(testStorageDir)) {
    fs.rmSync(testStorageDir, { recursive: true, force: true });
  }
});

// Mock console methods in tests
global.console = {
  ...console,
  log: jest.fn(),
  debug: jest.fn(),
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
};

// Note: node-fetch mocking is handled per-test to avoid conflicts

// Mock proper-lockfile for tests to avoid filesystem locking issues
jest.unstable_mockModule('proper-lockfile', () => ({
  default: {
    lock: jest.fn(() => Promise.resolve()),
    unlock: jest.fn(() => Promise.resolve()),
  },
}));

// Mock process.stdout and process.stderr for MCP testing
const originalStdout = process.stdout.write;
const originalStderr = process.stderr.write;

beforeEach(() => {
  // Reset mocks before each test
  jest.clearAllMocks();
});

afterEach(() => {
  // Restore original methods
  process.stdout.write = originalStdout;
  process.stderr.write = originalStderr;
});