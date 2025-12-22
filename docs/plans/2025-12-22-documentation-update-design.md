# Documentation Update Design for v1.3.0

## Overview

Comprehensive documentation refresh and NPM publish preparation for mcp-perplexity-pro version 1.3.0.

## Scope

- Update CHANGELOG.md with all changes from PRs #6-10
- Update README.md tool documentation
- Remove deprecated `sonar-reasoning` model references
- Bump package.json version to 1.3.0

## Changes

### 1. CHANGELOG.md - Add 1.3.0 Section

```markdown
## [1.3.0] - 2025-12-22

### Added

- `check_async_perplexity`: New `include_content` parameter (default: `false`) to control whether full response content is returned, saving context for large research reports
- `check_async_perplexity`: New `save_report` parameter (default: `true`) to automatically save completed research reports
- `check_async_perplexity`: New `project_name` parameter for specifying where to save reports
- `check_async_perplexity`: Returns `report_path` when job completes, showing where report was saved

### Changed

- `research_perplexity`: `save_report` now defaults to `true` (previously required explicit opt-in)
- Updated to MCP SDK 1.25.1 for improved compatibility
- Removed deprecated `sonar-reasoning` model references

### Fixed

- `research_perplexity` now properly returns results through HTTP transport (was returning empty)
- Deep research with `sonar-deep-research` model now uses async API with polling to handle long-running queries
- Storage tests no longer have race conditions when running in parallel
- Resolved all Dependabot security alerts
```

### 2. README.md - Update check_async_perplexity Documentation

Expand the tool documentation to include new parameters:

```markdown
#### `check_async_perplexity`

Check status of async research job. By default, excludes full content to save context and auto-saves completed reports.

**Parameters:**

- `job_id` (required): Job identifier
- `include_content` (optional): Include full response content (default: `false` to save context)
- `save_report` (optional): Save completed report to project directory (default: `true`)
- `project_name` (optional): Project name for saving report (auto-detected if not provided)

**Returns:** Job status, and when complete: `report_path` showing where the report was saved.
```

### 3. README.md - Update research_perplexity Documentation

Note that `save_report` now defaults to `true`:

```markdown
- `save_report` (optional): Save report to project directory (default: `true`)
```

### 4. README.md - Remove Deprecated sonar-reasoning Model

Update model selection table:

| Query Type        | Selected Model        | Use Case                                                    |
| ----------------- | --------------------- | ----------------------------------------------------------- |
| Research requests | `sonar-deep-research` | "I need comprehensive research on..."                       |
| Real-time queries | `sonar-pro`           | "What's the current price of...", "Latest news..."          |
| Complex reasoning | `sonar-reasoning-pro` | "Analyze the implications of...", "Compare and contrast..." |
| Simple questions  | `sonar`               | Quick factual questions                                     |
| Default           | `sonar-reasoning-pro` | Fallback for all other queries                              |

Update model capabilities (remove sonar-reasoning):

```typescript
{
  "sonar": { search: true, reasoning: false, realTime: false, research: false },
  "sonar-pro": { search: true, reasoning: false, realTime: true, research: false },
  "sonar-reasoning-pro": { search: true, reasoning: true, realTime: true, research: false },
  "sonar-deep-research": { search: true, reasoning: true, realTime: false, research: true }
}
```

### 5. package.json - Version Bump

```json
"version": "1.3.0"
```

## NPM Publish Readiness

Already configured correctly:
- `main`: `dist/index.js`
- `bin`: Both CLI binaries defined
- `files`: Includes dist, bin, README, LICENSE
- `prepublishOnly`: Runs build, lint, tests

## Implementation Order

1. Update CHANGELOG.md
2. Update README.md tool documentation
3. Update README.md model tables
4. Bump package.json version
5. Build and test
6. Commit all changes
7. Create PR and merge
8. Publish to npm
