import { vi, beforeAll, afterAll, beforeEach, afterEach } from 'vitest';
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
  log: vi.fn(),
  debug: vi.fn(),
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
};

// Note: node-fetch mocking is handled per-test to avoid conflicts

// Mock proper-lockfile for tests to avoid filesystem locking issues
vi.mock('proper-lockfile', () => ({
  default: {
    lock: vi.fn(() => Promise.resolve()),
    unlock: vi.fn(() => Promise.resolve()),
  },
}));

// Mock process.stdout and process.stderr for MCP testing
const originalStdout = process.stdout.write;
const originalStderr = process.stderr.write;

beforeEach(() => {
  // Reset mocks before each test
  vi.clearAllMocks();
});

afterEach(() => {
  // Restore original methods
  process.stdout.write = originalStdout;
  process.stderr.write = originalStderr;
});
