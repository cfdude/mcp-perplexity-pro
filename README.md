# MCP Perplexity Pro

A comprehensive Model Context Protocol (MCP) server for the Perplexity API, featuring intelligent model selection, conversation management, and project-aware storage.

[![npm version](https://badge.fury.io/js/mcp-perplexity-pro.svg)](https://badge.fury.io/js/mcp-perplexity-pro)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![TypeScript](https://img.shields.io/badge/%3C%2F%3E-TypeScript-%230074c1.svg)](http://www.typescriptlang.org/)

## ✨ Features

- **🧠 Intelligent Model Selection**: Automatically chooses the optimal Perplexity model based on query analysis
- **💬 Conversation Management**: Stateful chat sessions with full conversation history
- **🔍 Comprehensive Search**: Access to all Perplexity models (sonar, sonar-pro, sonar-reasoning, sonar-reasoning-pro, sonar-deep-research)
- **📊 Async Operations**: Support for long-running research tasks
- **🗂️ Project-Aware Storage**: Conversations and reports stored in your project directory
- **🔒 Thread-Safe**: Concurrent access with file locking
- **🐳 Docker Ready**: Full Docker and Docker Compose support
- **📈 Production Ready**: Comprehensive error handling, logging, and monitoring
- **🧪 Well Tested**: Extensive unit and integration test coverage

## 🚀 Quick Start

### Prerequisites

- Node.js 20+
- Perplexity API key ([Get one here](https://perplexity.ai/))

### Installation

```bash
npm install -g mcp-perplexity-pro
```

### Configuration

Add to your Claude Desktop `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "perplexity-pro": {
      "command": "mcp-perplexity-pro",
      "config": {
        "api_key": "your-perplexity-api-key",
        "default_model": "sonar-reasoning-pro",
        "project_root": "/path/to/your/project",
        "storage_path": ".perplexity"
      }
    }
  }
}
```

## 📋 Available Tools

### Query Tools

#### `ask_perplexity`

Ask questions with intelligent model selection based on query type.

**Parameters:**

- `query` (required): Your question or prompt
- `model` (optional): Specific model to use
- `temperature` (optional): Response creativity (0.0-2.0)
- `max_tokens` (optional): Maximum response length

**Example:**

```
Ask Perplexity: "What are the latest developments in quantum computing?"
```

#### `research_perplexity`

Conduct comprehensive research with detailed reports saved to your project.

**Parameters:**

- `query` (required): Research topic or question
- `model` (optional): Defaults to `sonar-deep-research`
- `save_report` (optional): Save detailed report to project

**Example:**

```
Research: "Market analysis of renewable energy trends in 2024"
```

### Chat Tools

#### `chat_perplexity`

Start or continue conversations with full context.

**Parameters:**

- `message` (required): Your message
- `chat_id` (optional): Continue existing conversation
- `title` (optional): Title for new conversation
- `model` (optional): Model selection

**Example:**

```
Chat: "Hello, I'd like to discuss AI ethics" (title: "AI Ethics Discussion")
```

#### `list_chats_perplexity`

List all conversations in your project.

#### `read_chat_perplexity`

Retrieve full conversation history.

**Parameters:**

- `chat_id` (required): Conversation ID

### Async Tools

#### `async_perplexity`

Create long-running research jobs for complex queries.

**Parameters:**

- `query` (required): Research question
- `model` (optional): Defaults to `sonar-deep-research`

#### `check_async_perplexity`

Check status of async research job.

**Parameters:**

- `job_id` (required): Job identifier

#### `list_async_jobs`

List all async jobs in your project.

### Utility Tools

#### `storage_stats_perplexity`

Get storage statistics and usage information.

#### `model_info_perplexity`

Get information about available models and their capabilities.

## 🧠 Intelligent Model Selection

The server automatically selects the optimal model based on query analysis:

| Query Type        | Selected Model        | Use Case                                                    |
| ----------------- | --------------------- | ----------------------------------------------------------- |
| Research requests | `sonar-deep-research` | "I need comprehensive research on..."                       |
| Real-time queries | `sonar-pro`           | "What's the current price of...", "Latest news..."          |
| Complex reasoning | `sonar-reasoning-pro` | "Analyze the implications of...", "Compare and contrast..." |
| Simple questions  | `sonar-reasoning`     | General questions                                           |
| Default           | `sonar-reasoning-pro` | Fallback for all other queries                              |

### Model Capabilities

```typescript
{
  "sonar": {
    search: true, reasoning: false, realTime: false, research: false
  },
  "sonar-pro": {
    search: true, reasoning: false, realTime: true, research: false
  },
  "sonar-reasoning": {
    search: true, reasoning: true, realTime: false, research: false
  },
  "sonar-reasoning-pro": {
    search: true, reasoning: true, realTime: true, research: false
  },
  "sonar-deep-research": {
    search: true, reasoning: true, realTime: false, research: true
  }
}
```

## 🗂️ Project-Aware Storage

All conversations and research reports are stored in your project directory:

```
your-project/
├── .perplexity/
│   ├── chats/
│   │   ├── chat-uuid-1.json
│   │   └── chat-uuid-2.json
│   ├── reports/
│   │   ├── research-report-1.json
│   │   └── research-report-2.json
│   └── async-jobs/
│       ├── job-uuid-1.json
│       └── job-uuid-2.json
```

### Storage Features

- **Thread-safe**: File locking prevents concurrent access issues
- **Session-aware**: Multiple sessions can work with the same project
- **Organized**: Separate directories for different content types
- **Persistent**: All data survives server restarts
- **Portable**: Easy to backup, move, or version control

## 🐳 Docker Deployment

### Development

```bash
# Clone repository
git clone https://github.com/cfdude/mcp-perplexity-pro.git
cd mcp-perplexity-pro

# Start development environment
docker-compose --profile dev up -d
```

### Production

```bash
# Set environment variables
export PROJECT_ROOT=/path/to/your/project

# Start production environment
docker-compose up -d
```

### Custom Docker

```dockerfile
FROM mcp-perplexity-pro:latest

# Custom configuration
COPY my-config.json /app/config.json

# Custom entrypoint
CMD ["node", "dist/index.js", "--config", "config.json"]
```

## ⚙️ Configuration

### Environment Variables

| Variable             | Description          | Default               |
| -------------------- | -------------------- | --------------------- |
| `NODE_ENV`           | Environment mode     | `development`         |
| `PERPLEXITY_API_KEY` | Your API key         | Required              |
| `PROJECT_ROOT`       | Project directory    | Current directory     |
| `STORAGE_PATH`       | Storage subdirectory | `.perplexity`         |
| `DEFAULT_MODEL`      | Default model        | `sonar-reasoning-pro` |
| `SESSION_ID`         | Session identifier   | Auto-generated        |

### Advanced Configuration

```json
{
  "api_key": "your-key",
  "default_model": "sonar-reasoning-pro",
  "project_root": "/workspace",
  "storage_path": ".perplexity",
  "session_id": "unique-session",
  "request_timeout": 30000,
  "max_retries": 3,
  "rate_limit": {
    "requests_per_minute": 60,
    "concurrent_requests": 5
  }
}
```

## 🧪 Development

### Setup

```bash
# Clone and install
git clone https://github.com/cfdude/mcp-perplexity-pro.git
cd mcp-perplexity-pro
npm install

# Development mode
npm run dev

# Run tests
npm test
npm run test:coverage

# Linting and formatting
npm run lint
npm run format
```

### Project Structure

```
src/
├── index.ts              # Main MCP server
├── types.ts              # TypeScript definitions
├── models.ts             # Model registry & selection
├── perplexity-api.ts     # API client wrapper
├── storage.ts            # Storage management
└── tools/
    ├── query.ts          # Query tools
    ├── chat.ts           # Chat tools
    └── async.ts          # Async tools

tests/
├── models.test.ts        # Model selection tests
├── storage.test.ts       # Storage tests
├── perplexity-api.test.ts # API tests
└── integration.test.ts   # End-to-end tests
```

### Testing

```bash
# Run all tests
npm test

# Watch mode
npm run test:watch

# Coverage report
npm run test:coverage

# Specific test file
npm test -- models.test.ts
```

## 📊 API Usage Examples

### Basic Query

```javascript
// Simple question
const result = await askPerplexity({
  query: 'What is machine learning?',
});

// With specific model
const result = await askPerplexity({
  query: 'Current Bitcoin price',
  model: 'sonar-pro',
});
```

### Conversation

```javascript
// Start new conversation
const chat = await chatPerplexity({
  message: 'Hello!',
  title: 'General Discussion',
});

// Continue conversation
const response = await chatPerplexity({
  chat_id: chat.id,
  message: 'Tell me about quantum computing',
});
```

### Research

```javascript
// Comprehensive research
const research = await researchPerplexity({
  query: 'Impact of AI on healthcare industry',
  save_report: true,
});

// Async research for complex topics
const job = await asyncPerplexity({
  query: 'Detailed analysis of climate change solutions',
});

// Check job status
const status = await checkAsync({
  job_id: job.id,
});
```

## 🔒 Security

### API Key Management

- Store API keys securely using environment variables
- Never commit API keys to version control
- Rotate keys regularly
- Use different keys for different environments

### Network Security

- HTTPS in production
- Rate limiting implemented
- Input validation and sanitization
- Error handling without information leakage

### Container Security

- Non-root user execution
- Minimal base images
- Regular security updates
- Vulnerability scanning

## 📈 Monitoring

### Health Checks

```bash
# Basic health check
curl http://localhost:3000/health

# Detailed status
curl http://localhost:3000/status
```

### Metrics

The server exposes Prometheus-compatible metrics:

- Request count and duration
- Error rates by endpoint
- Storage usage statistics
- Model usage distribution

### Logging

Structured JSON logging with configurable levels:

```json
{
  "timestamp": "2024-08-20T19:00:00.000Z",
  "level": "info",
  "message": "Query processed successfully",
  "model": "sonar-reasoning-pro",
  "duration": 1250,
  "session_id": "session-123"
}
```

## 🚨 Troubleshooting

### Common Issues

**API Key Errors**

```bash
Error: Invalid API key
Solution: Verify PERPLEXITY_API_KEY is set correctly
```

**Storage Permission Errors**

```bash
Error: EACCES: permission denied
Solution: Ensure storage directory is writable
```

**Model Selection Issues**

```bash
Error: Model not available
Solution: Check model name spelling and availability
```

### Debug Mode

```bash
DEBUG=mcp-perplexity:* npm start
```

### Support

- 📚 [Documentation](https://github.com/cfdude/mcp-perplexity-pro/wiki)
- 🐛 [Issues](https://github.com/cfdude/mcp-perplexity-pro/issues)
- 💬 [Discussions](https://github.com/cfdude/mcp-perplexity-pro/discussions)

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Development Workflow

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

### Code Standards

- TypeScript with strict mode
- ESLint + Prettier formatting
- 100% test coverage for new features
- Conventional commit messages

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Perplexity AI](https://perplexity.ai/) for providing the excellent API
- [Model Context Protocol](https://github.com/modelcontextprotocol) for the MCP specification
- [Smithery](https://smithery.ai/) for MCP development tools
- The open-source community for inspiration and contributions

## 📊 Project Stats

![GitHub stars](https://img.shields.io/github/stars/cfdude/mcp-perplexity-pro)
![GitHub forks](https://img.shields.io/github/forks/cfdude/mcp-perplexity-pro)
![GitHub issues](https://img.shields.io/github/issues/cfdude/mcp-perplexity-pro)
![GitHub pull requests](https://img.shields.io/github/issues-pr/cfdude/mcp-perplexity-pro)

---

**Built with ❤️ for the MCP community**
