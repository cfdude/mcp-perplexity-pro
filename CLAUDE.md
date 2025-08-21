# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Core Development
```bash
# Install dependencies
npm install

# Development mode with hot reload
npm run dev

# Build TypeScript and create distributable
npm run build

# Start the built server
npm start

# Type checking without emitting files
npm run type-check
```

### Testing
```bash
# Run all tests
npm test

# Run tests in watch mode for development
npm run test:watch

# Generate coverage report
npm run test:coverage

# Run specific test file
npm test -- models.test.ts
```

### Code Quality
```bash
# Run ESLint
npm run lint

# Fix auto-fixable ESLint issues
npm run lint:fix

# Format code with Prettier
npm run format

# Check if code is properly formatted
npm run format:check
```

### Docker Development
```bash
# Build Docker image
npm run docker:build

# Start with Docker Compose
npm run docker:run

# Development environment
docker-compose --profile dev up -d
```

## Architecture Overview

### MCP Server Architecture
This is a Model Context Protocol (MCP) server that provides intelligent access to the Perplexity API. The architecture follows MCP specifications with TypeScript SDK integration.

**Core Components:**
- **Main Server (`src/index.ts`)**: MCP server implementation using `McpServer` from `@modelcontextprotocol/sdk`
- **Model Registry (`src/models.ts`)**: Intelligent model selection system that analyzes queries and selects optimal Perplexity models
- **API Client (`src/perplexity-api.ts`)**: Wrapper around Perplexity API with error handling and rate limiting
- **Storage System (`src/storage.ts`)**: Thread-safe file-based storage with project-aware organization
- **Project Manager (`src/project-manager.ts`)**: Manages multiple project contexts and storage isolation

### Tool Categories
The server exposes 5 categories of MCP tools:

1. **Query Tools** (`src/tools/query.ts`):
   - `ask_perplexity`: Stateless queries with intelligent model selection
   - `research_perplexity`: Deep research with report saving

2. **Chat Tools** (`src/tools/chat.ts`):
   - `chat_perplexity`: Conversational interface with persistent storage
   - `list_chats_perplexity`: List stored conversations
   - `read_chat_perplexity`: Retrieve conversation history
   - `storage_stats_perplexity`: Storage usage statistics

3. **Async Tools** (`src/tools/async.ts`):
   - `async_perplexity`: Long-running research jobs
   - `check_async_perplexity`: Job status checking
   - `list_async_jobs`: List all async operations

4. **Project Tools** (`src/tools/projects.ts`):
   - `list_projects_perplexity`: List all projects
   - `delete_project_perplexity`: Safe project deletion

5. **Utility Tools**:
   - `model_info_perplexity`: Model capabilities and selection guidance

### Intelligent Model Selection
The system analyzes queries using keyword patterns and complexity heuristics to automatically select from:

- **sonar**: Fast, cost-effective for simple queries
- **sonar-pro**: Advanced search with real-time capabilities
- **sonar-reasoning**: Reasoning with search capabilities
- **sonar-reasoning-pro**: Complex analysis and multi-step reasoning (default)
- **sonar-deep-research**: Comprehensive research and literature reviews

### Project-Aware Storage
Storage is organized per project with thread-safe file locking:
```
{project_root}/.perplexity/
├── chats/           # Conversation storage
├── reports/         # Research reports
└── async-jobs/      # Background job tracking
```

## TypeScript Configuration

The project uses strict TypeScript with:
- `exactOptionalPropertyTypes`: true (requires careful handling of optional properties)
- ES2022 target with ESNext modules
- Comprehensive strict mode settings
- Declaration files generation for library use

## Important Development Notes

### MCP SDK Integration
- Uses `@modelcontextprotocol/sdk` version 0.6.0 (note: version in package.json may be outdated)
- Imports from `/dist/esm/server/` paths for proper ESM support
- Tool schemas must be defined as plain objects (not Zod .shape)

### Error Handling Patterns
- All async operations include comprehensive error handling
- API errors are categorized by type (rate_limit, invalid_model, etc.)
- Storage operations use file locking for thread safety

### Testing Strategy
- Unit tests for individual components
- Integration tests for MCP tool functionality
- Mock implementations for external API calls
- Coverage requirements for new features

### Key Dependencies
- `@modelcontextprotocol/sdk`: MCP server implementation
- `zod`: Runtime type validation and schema definitions
- `proper-lockfile`: Thread-safe file operations
- `node-fetch`: HTTP client for Perplexity API
- `uuid`: Unique identifier generation

## Configuration

Environment variables and config schema defined in `src/types.ts`:
- `api_key`: Perplexity API key (required)
- `default_model`: Default model selection (sonar-reasoning-pro)
- `project_root`: Base directory for storage
- `storage_path`: Subdirectory for MCP data (.perplexity)
- `session_id`: Optional session identifier

## Smithery Integration

Uses Smithery for MCP development tooling:
- `smithery dev`: Development server with hot reload
- `smithery build`: Production build optimization
- Configuration in `smithery.config.js`