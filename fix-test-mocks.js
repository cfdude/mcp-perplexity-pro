const fs = require('fs');

// Read the test file
let content = fs.readFileSync(
  '/Users/robsherman/Servers/mcp-perplexity-pro/tests/perplexity-api.test.ts',
  'utf8'
);

// Fix all remaining simple mock patterns
const simpleMockPattern =
  /mockFetch\.mockResolvedValueOnce\(\{\s*ok:\s*(true|false),\s*status:\s*(\d+),\s*json:\s*async\s*\(\)\s*=>\s*([^,\}]+),?\s*\}\s*as\s*Response\);/g;

content = content.replace(simpleMockPattern, (match, ok, status, jsonReturn) => {
  const isSuccess = ok === 'true';
  const statusText =
    {
      200: 'OK',
      400: 'Bad Request',
      404: 'Not Found',
      429: 'Too Many Requests',
      500: 'Internal Server Error',
    }[status] || 'Unknown';

  return `const mockHeaders = new Map();
      mockHeaders.set('content-type', 'application/json');
      
      mockFetch.mockResolvedValueOnce({
        ok: ${ok},
        status: ${status},
        statusText: '${statusText}',
        headers: {
          get: (name: string) => mockHeaders.get(name.toLowerCase()) || null,
        },
        json: async () => ${jsonReturn},
        text: async () => JSON.stringify(${jsonReturn}),
      } as Response);`;
});

// Write the fixed content back
fs.writeFileSync(
  '/Users/robsherman/Servers/mcp-perplexity-pro/tests/perplexity-api.test.ts',
  content
);
console.log('Fixed test mocks');
