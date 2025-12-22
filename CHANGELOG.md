# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2025-09-16

### Added

- **Transport Mode Arguments**: New `--transport` argument for explicit deployment mode control
  - `--transport=stdio`: Force stdio transport mode
  - `--transport=http`: Force HTTP transport mode
  - `--transport=auto`: Auto-detect transport mode (default)
- **Unified NPX Usage**: Single `mcp-perplexity-pro` package works for all deployment modes
- **Auto-detection**: Intelligent stdio/HTTP mode detection based on environment
- **Enhanced Help**: Comprehensive help text with transport mode examples
- **Backward Compatibility**: Existing `mcp-perplexity-pro-stdio` binary still supported

### Changed

- **README.md**: Updated with new transport argument examples and usage patterns
- **Default Behavior**: Auto-detect mode is now default, choosing best transport for environment
- **Documentation**: Enhanced deployment examples showing transport mode usage

### Fixed

- **NPX Configuration**: Users can now use `npx mcp-perplexity-pro --transport=stdio` in MCP configs
- **Deployment Flexibility**: Single package name works across all transport modes

## [1.1.0] - 2025-01-29

### Added

- **stdio-npx deployment support**: New `mcp-perplexity-pro-stdio` binary for NPX-based deployments
- **stdio-docker deployment support**: Docker container with stdio transport via `Dockerfile.stdio`
- NPX deployment option with `npx mcp-perplexity-pro-stdio` command
- Docker stdio service in docker-compose.yml with profile support
- Comprehensive deployment documentation for both stdio-npx and stdio-docker
- Docker stdio entrypoint script with environment validation

### Changed

- Updated README.md with detailed deployment instructions for all transport options
- Enhanced package.json with stdio binary and Docker build scripts
- Improved Docker Compose configuration with multiple service profiles

## [1.0.0] - 2025-08-25

### Changed

- **BREAKING CHANGE**: Migrated from stdio to HTTP-only transport
- Unified launcher that works with both Claude Code and Claude Desktop
- Simplified configuration with automatic build detection

### Added

- Universal launcher (`src/launcher.ts`) with automatic build detection
- Shared server logic (`src/mcp-server.ts`) for code reuse
- NPM package structure with bin field for global installation
- HTTP transport configuration for both clients

### Removed

- stdio transport support (deprecated by Anthropic)
- Separate server implementations for different transports

### Fixed

- Alignment with Anthropic's direction away from stdio transport
- Simplified port management and configuration

## [0.1.0] - Previous Version

- Initial implementation with dual stdio/HTTP transport support
