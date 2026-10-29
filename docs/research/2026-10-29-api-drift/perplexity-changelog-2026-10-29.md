> ## Documentation Index
> Fetch the complete documentation index at: https://docs.perplexity.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Changelog

> Updates to the Perplexity API platform.

> [!TIP]
>
> Have a feature request? Post it in the [Feature Requests](https://community.perplexity.ai/c/ideas/11) category on our community forum.

**October 2026**

**Agent API: effort level updates and the `ultra-preview` effort level**

These effort level changes were not listed in earlier changelog entries. Each line names the current version. Earlier versions stay available as [pinned versions](https://docs.perplexity.ai/docs/agent-api/effort.md#pinning-an-effort-level-version).

* **`fast` (`fast@2026-10-16.0`):** falls back to `openai/gpt-5.6-luna` when `openai/gpt-6-luna` is unavailable.
* **`low` (`low@2026-10-24.0`):** max output tokens rise from 32,768 to 128,000. `web_search` `max_tokens` and `max_tokens_per_page` rise from 2,000 to 4,000. `fetch_url` content extraction uses `openai/gpt-6-luna`.
* **`medium` (`medium@2026-10-22.1`):** `web_search` `max_tokens` and `max_tokens_per_page` rise from 2,000 to 4,000. `fetch_url` content extraction uses `openai/gpt-6-luna`.
* **`high` (`high@2026-10-28.0`):** uses `openai/gpt-6.1-terra` instead of `openai/gpt-6-sol`. Max steps rise from 15 to 40, and a run makes at most 40 tool calls. `web_search` `max_tokens` and `max_tokens_per_page` rise from 2,000 to 4,000. `fetch_url` content extraction uses `openai/gpt-6-luna`.
* **`xhigh` (`xhigh@2026-10-29.0`):** stays on `anthropic/claude-opus-5-5`, with `openai/gpt-6.1-sol` as the fallback model. Max steps rise from 100 to 300, and context compaction starts at 150,000 tokens. `xhigh` sets no system prompt, so its frozen configuration no longer sends `instructions`.
* **Step budget reminders:** `low`, `medium`, `high`, and `xhigh` remind the model of its remaining step budget as it works. `fast` runs one step and has no reminders.

**New: `ultra-preview`.** An effort level for broad research and data-gathering tasks where coverage matters most. Runs can take a long time. Call it by name with `effort="ultra-preview"`.

The undocumented `ultra` effort name is removed and now returns an error. The `wide-research` alias now selects `xhigh`.

`max_steps` now accepts values up to 500, up from 100. If you use a [frozen configuration](https://docs.perplexity.ai/docs/agent-api/effort.md#current-effort-level-values), copy the updated values to keep matching each effort level's public API fields. See [Effort](https://docs.perplexity.ai/docs/agent-api/effort.md).

**October 2026**

**Agent API: `preset` renamed to `effort`**

This is a naming change only. Effort levels keep the same models, prompts, tools, limits, and pricing. Version pinning and frozen configurations continue to work as before. `preset` is still accepted as a deprecated alias, and responses return both fields. See [Effort](https://docs.perplexity.ai/docs/agent-api/effort.md).

The Python SDK 0.46.0 and TypeScript SDK 0.41.0 add the `effort` parameter.

**October 2026**

**Tool approvals for MCP and connector calls**

Set `require_approval` on an `mcp` or `connector` tool to review calls before they run. A call that needs approval returns an `mcp_approval_request` item and does not run. To approve or deny it, send an `mcp_approval_response` with `previous_response_id`. Use `"always"` to review every call, or a filter object to skip approval for selected tools or for read-only tools. Calls still run without approval by default.

The Python SDK 0.43.8 and TypeScript SDK 0.38.8 include the approval types. See [MCP approvals](https://docs.perplexity.ai/docs/agent-api/tools/mcp.md#approvals) and [Connectors](https://docs.perplexity.ai/docs/agent-api/tools/connectors.md).

**October 2026**

**Older models removed from the model docs; GPT-6 Astra and DeepSeek V4 Pro added**

The following models are no longer listed in the Agent API model docs, pricing calculator, or examples:

* **Anthropic:** `anthropic/claude-opus-4-8`, `anthropic/claude-opus-4-7`, `anthropic/claude-opus-4-6`, `anthropic/claude-opus-4-5`, `anthropic/claude-sonnet-4-6`, `anthropic/claude-sonnet-4-5`, and `anthropic/claude-haiku-4-5`
* **Google:** `google/gemini-3-flash-preview`, `google/gemini-3.1-pro-preview`, `google/gemini-3.1-flash-lite`, `google/gemini-3.5-flash`, and `google/gemini-3.5-flash-lite`
* **xAI:** `xai/grok-4.3`, `xai/grok-4.20-reasoning`, `xai/grok-4.20-non-reasoning`, and `xai/grok-4.20-multi-agent`

For new integrations, use `anthropic/claude-opus-5-5`, `anthropic/claude-sonnet-5-5`, `anthropic/claude-haiku-5-5`, `google/gemini-4-argon`, `google/gemini-3.8-flash`, or `xai/grok-4.7`.

The model docs now also list `openai/gpt-6-astra` (\$10.00 per million input tokens and \$50.00 per million output tokens up to 272k input tokens, with `flex` and `priority` tiers) and `perplexity/deepseek-v4-pro-0813` (\$1.32 per million input tokens, \$0.044 per million cached input tokens, and \$3.96 per million output tokens), which is also available through the Orchestrator API. See the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

**October 2026**

**Gemini 4 Argon**

The Agent API now supports `google/gemini-4-argon`. Introductory pricing through November 30, 2026 is \$2.00 per million input tokens, \$0.10 per million cached input tokens, and \$10.00 per million output tokens, including reasoning tokens. See the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

**October 2026**

**NVIDIA Nemotron 3.5 Super**

The Agent API now supports `perplexity/nemotron-3.5-super-120b-a12b` at \$0.20 per million input tokens, \$0.04 per million cached input tokens, and \$0.50 per million output tokens. It has a 1,048,576-token context window, returns up to 131,072 output tokens, and accepts text input only. It replaces `perplexity/nemotron-3-ultra-550b-a55b`, which is no longer listed in the Agent API or Orchestrator API model docs. See the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

**October 2026**

**xhigh preset output budget raised to 512,000 tokens**

The Agent API `xhigh` preset now allows up to 512,000 output tokens, up from 128,000. If you use a [frozen configuration](https://docs.perplexity.ai/docs/agent-api/presets.md#current-preset-values), update `max_output_tokens` to keep matching the preset.

Correction: `xhigh` has used Fast Search since the October update that moved `low`, `medium`, and `high` to Fast Search. That entry now lists `xhigh` too.

**October 2026**

**Claude Haiku 5.5**

The Agent API now supports `anthropic/claude-haiku-5-5`. Requests with more than 100k input tokens use higher rates. See the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

**October 2026**

**Decisions API: pplx-decider-v1.2 and pplx-decider-flash-v1.2**

`pplx-decider-v1.2` replaces `pplx-decider-v1.1-27b` as the 27B decision model, at \$0.02 per million input tokens. `pplx-decider-flash-v1.2` is a new 4B decision model at \$0.01 per million input tokens. Both accept text and images and use the same request limits. Output tokens stay free.

Use `pplx-decider-latest` or `pplx-decider-flash-latest` to follow the newest version of each model. `perplexity/pplx-decider-latest` and `perplexity/pplx-decider-flash-latest` are also accepted. Requests that name `pplx-decider-v1.1-27b` or `pplx-decider-v1-27b` continue to work and select `pplx-decider-v1.2`. See [When to use each](https://docs.perplexity.ai/docs/decisions/quickstart.md#when-to-use-each) and [Pricing](https://docs.perplexity.ai/docs/getting-started/pricing.md).

**October 2026**

**Decisions API: pplx-decider-v1.1-27b replaces v1**

`pplx-decider-v1.1-27b` replaces `pplx-decider-v1-27b` as the Decisions API model. Input now costs \$0.02 per million tokens, down from \$0.04.

Use `pplx-decider-v1.1-27b` in new requests. Requests that still name `pplx-decider-v1-27b` continue to work and bill at the same \$0.02 rate. See [Pricing](https://docs.perplexity.ai/docs/getting-started/pricing.md) and the [Decisions API quickstart](https://docs.perplexity.ai/docs/decisions/quickstart.md).

**October 2026**

**New: Decisions API**

The Decisions API answers questions about text, JSON, or images with probabilities instead of generated text. Use `POST /v1/decisions` with `pplx-decider-v1-27b` for yes-or-no, choice, or scored answers that application code can act on directly.

Input costs \$0.04 per million tokens. Output tokens are free, with no per-request fee. See the [Decisions API quickstart](https://docs.perplexity.ai/docs/decisions/quickstart.md).

**October 2026**

**Native document input**

The Agent API now accepts PDF, DOC, DOCX, TXT, and RTF documents as `input_file` content. Send a document inline with `file_data` or provide a public HTTPS `file_url`. For inline documents, continue the conversation with `previous_response_id` without uploading the file again. See [Working with Files](https://docs.perplexity.ai/docs/agent-api/working-with-files.md).

**October 2026**

**Image Search**

The new `image_search` tool searches for images on the web and returns typed `image_search_results` with image and source-page URLs. Use result limits plus domain, format, and safe-search filters to control the results.

Usage reports successful calls at \$2.50 per 1,000 invocations; failed calls have zero tool cost. See [Agent API Image Search](https://docs.perplexity.ai/docs/agent-api/tools/image-search.md).

**October 2026**

**Accurate sandbox extraction usage and costs**

Agent API responses now include model token usage and cost for successful `pplx_sdk.llm.extract` calls made inside the `sandbox` tool. Per-model tokens appear in `usage.tool_calls_details.sandbox.token_usage`. The reported extraction cost appears in `usage.tool_calls_details.sandbox.cost_usd` and `usage.cost.tool_calls_cost_details.sandbox`, and contributes to `usage.cost.total_cost`.

Sandbox extraction uses the existing [`openai/gpt-6-luna` pricing](https://docs.perplexity.ai/docs/agent-api/models), including cache creation, cache read, and reasoning-token dimensions. This corrects response-level usage and cost reporting; it does not change pricing or backfill historical responses.

**October 2026**

**Low, medium, high, and xhigh presets use Fast Search**

The Agent API `low`, `medium`, `high`, and `xhigh` presets now use Fast Search (`search_type: "fast"`) for `web_search`, matching the `fast` preset. `web_search` calls made under these presets drop from \$2.50 to \$1.00 per 1,000 invocations, and search is about 800 ms faster.

Models, prompts, tool budgets, and step limits are unchanged. To keep standard web search under any preset, set `search_type: "web"` on the `web_search` tool. See [Agent API Web Search](https://docs.perplexity.ai/docs/agent-api/tools/web-search.md#search-type).

**September 2026**

**GPT-6.1 Sol**

The Agent API now supports `openai/gpt-6.1-sol`. See the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

**September 2026**

**Claude Sonnet 5.5**

The Agent API now supports `anthropic/claude-sonnet-5-5`. See the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

**September 2026**

**xhigh preset uses Claude Opus 5.5**

The Agent API `xhigh` preset now uses Claude Opus 5.5:

| Preset | Previous model | New model |
| - | - | - |
| `xhigh` | `openai/gpt-5.6-sol` | `anthropic/claude-opus-5-5` |

Prompts, reasoning effort, tools, token budgets, and step limits are unchanged.

**September 2026**

**Low, medium, and high presets use GPT-6**

The Agent API `low`, `medium`, and `high` presets now use the GPT-6 model family:

| Preset | Previous model | New model |
| - | - | - |
| `low` | `openai/gpt-5.6-luna` | `openai/gpt-6-luna` |
| `medium` | `openai/gpt-5.6-luna` | `openai/gpt-6-luna` |
| `high` | `openai/gpt-5.6-sol` | `openai/gpt-6-sol` |

Prompts, reasoning effort, tools, token budgets, and step limits are unchanged.

**September 2026**

**Upcoming retirement of older OpenAI models**

On October 24, 2026 at 00:00 UTC, the Agent API and Orchestrator API will retire these model IDs:

* `openai/gpt-5.4`
* `openai/gpt-5.4-mini`
* `openai/gpt-5.4-nano`
* `openai/gpt-5.2`
* `openai/gpt-5.1`
* `openai/gpt-5`
* `openai/gpt-5-mini`

Update direct model selections and fallback chains before the cutoff. The models remain available until then. After the cutoff, the retired IDs will no longer be accepted or returned by model-list endpoints.

For new integrations, choose a current OpenAI model in the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

**September 2026**

**Fast preset uses Fast Search**

The Agent API `fast` preset now uses Fast Search (`search_type: "fast"`). `web_search` drops from \$2.50 to \$1.00 per 1,000 invocations, and search is about 800 ms faster. See [Agent API Web Search](https://docs.perplexity.ai/docs/agent-api/tools/web-search.md#search-type).

**September 2026**

**Fast Search**

Set `search_type: "fast"` on the Search API or the Agent API `web_search` tool to use a lower-latency search path. Fast Search costs \$1.00 per 1,000 Search API requests or `web_search` invocations, with model tokens billed separately for Agent API. Set `search_type: "web"` for standard web search. See [Search API Fast Search](https://docs.perplexity.ai/docs/search/fast-search.md) or [Agent API Web Search](https://docs.perplexity.ai/docs/agent-api/tools/web-search.md#search-type).

**September 2026**

**GPT-6 Sol**

The Agent API now supports `openai/gpt-6-sol`. See the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

**GPT-6 Luna**

The Agent API now supports `openai/gpt-6-luna`. See the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

**Claude Opus 5.5**

The Agent API now supports `anthropic/claude-opus-5-5`. See the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

**Grok 4.7**

The Agent API now supports `xai/grok-4.7`. See the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

**September 2026**

**Custom connectors: Bring your own MCP server**

Register a remote MCP server once on your [Project connectors page](https://console.perplexity.ai/project/connectors).
Perplexity stores the server's credential, so your application does not need to store or send it with each request.
Use the generated connector ID with `type: "connector"` in Agent API requests.
Custom connectors are available to all Projects and support API-key or no authentication, with Streamable HTTP or SSE transport.
See [Add a custom connector](https://docs.perplexity.ai/docs/agent-api/tools/connectors.md#add-a-custom-connector).

**September 2026**

**Sign in with Perplexity for the remote MCP server**

The [remote Perplexity MCP Server](https://docs.perplexity.ai/docs/getting-started/integrations/mcp-server.md) now supports OAuth. Add `https://api.perplexity.ai/mcp` to any MCP client that supports OAuth, such as claude.ai, Claude Code, Cursor, or VS Code, and sign in with your Perplexity account instead of pasting an API key. You choose which API organization to bill during sign-in. API keys continue to work for clients without OAuth support.

**September 2026**

**Gemini 3.8 Flash**

The Agent API now supports `google/gemini-3.8-flash`. Promotional pricing through December 31, 2026 is \$0.75 per million uncached-input tokens, \$0.075 per million cached-input tokens, and \$3.75 per million output and reasoning tokens. See the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

**September 2026**

**GLM 5.3 Flash**

The Agent API and Orchestrator API now support `perplexity/glm-5.3-flash` at \$0.15 per million uncached-input tokens, \$0.03 per million cached-input tokens, and \$0.50 per million output tokens. See the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md) or the [Router model catalog](https://docs.perplexity.ai/docs/router/models.md).

**August 2026**

**GLM 5.3**

The Agent API and Orchestrator API now support `perplexity/glm-5.3` at \$1.40 per million uncached-input tokens, \$0.26 per million cached-input tokens, and \$4.40 per million output tokens. See the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md) or the [Router model catalog](https://docs.perplexity.ai/docs/router/models.md).

**August 2026**

**Prompt caching for presets**

Agent API presets now use stable prompt cache keys automatically, allowing independent requests with the same preset to reuse the shared prompt prefix (system prompt and tool definitions). No request changes are required, and an explicit `prompt_cache_key` still overrides the preset default. This can reduce costs by about 5% for applications that use presets frequently, depending on cache utilization. The [current preset values](https://docs.perplexity.ai/docs/agent-api/presets.md#current-preset-values) include each key for frozen configurations.

**August 2026**

**Fast preset updated**

The Agent API `fast` preset now uses `openai/gpt-6-luna` with reasoning effort set to `none` and priority processing. Dynamic `fast` preset requests pick up the change automatically. If you use a [frozen configuration](https://docs.perplexity.ai/docs/agent-api/presets.md#current-preset-values), update the model and reasoning effort and set `service_tier` to `priority`. Priority processing uses 2× the model's standard token prices.

**August 2026**

**Gemini 3.7 Flash**

Pricing for `google/gemini-3.7-flash` increased on August 27, 2026 to \$0.75 per million input tokens, \$0.075 per million cached-input tokens, and \$3.75 per million output and reasoning tokens. See the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

**August 2026**

**Grok 4.6**

The Agent API now supports `xai/grok-4.6`, xAI's latest flagship reasoning and agentic model. See pricing in the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

**August 2026**

**NVIDIA Nemotron 3 Ultra**

The Agent API and Orchestrator API now support `perplexity/nemotron-3-ultra-550b-a55b` at \$0.25 per million input or cached-input tokens and \$2.50 per million output tokens. See the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md) or the [Router model catalog](https://docs.perplexity.ai/docs/router/models.md).

**July 2026**

**GPT-5.6 price cuts and Sol Fast mode**

GPT-5.6 Luna now costs \$0.20 per million input tokens and \$1.20 per million output tokens. GPT-5.6 Terra now costs \$2 per million input tokens and \$12 per million output tokens. GPT-5.6 Sol now supports Fast mode at 2× standard token pricing; send `service_tier: "priority"` to use it.

**July 2026**

**New: Orchestrator API**

Unified access to open-weight models hosted by Perplexity through a single endpoint — with your existing Perplexity API key.

**Key features:**

* OpenAI Chat Completions and Anthropic Messages compatibility: switching is a base-URL change
* Automatic health-based routing and failover across model deployments
* Per-token pricing at each model's published rates, with no per-request fees

[Get started with the Orchestrator API →](https://docs.perplexity.ai/docs/router/quickstart.md)

**July 2026**

**Remote MCP Server**

The [Perplexity MCP Server](https://docs.perplexity.ai/docs/getting-started/integrations/mcp-server.md) is now available as a remote server hosted by Perplexity at `https://api.perplexity.ai/mcp`. Connect any MCP client that supports Streamable HTTP using your API key as a bearer token, with no local installation and nothing to update. Tools and behavior are identical to the local server, and usage is billed to your API key at standard API pricing.

**July 2026**

**Low preset updated**

The Agent API `low` preset now uses `openai/gpt-5.6-luna` with `minimal` reasoning effort and a 32,768-token maximum output. If you use a [frozen configuration](https://docs.perplexity.ai/docs/agent-api/presets.md#current-preset-values), update these values to match the current preset. Dynamic `low` preset requests pick up the change automatically.

**July 2026**

**Inline citations for research presets**

The Agent API's search-backed presets include inline citations: `fast` cites claims drawn from search results with numbered citations such as `[1]`, while `low`, `medium`, and `high` now cite claims drawn from tool results or provided source artifacts with source-typed citations such as `[web:1]`. After a successful tool call, the `low`, `medium`, and `high` presets include at least one citation in the final answer. The [current preset values](https://docs.perplexity.ai/docs/agent-api/presets.md#current-preset-values) include the system prompts for frozen configurations.

**July 2026**

**MCP Server 1.0: now backed by the Agent API**

The [Perplexity MCP Server](https://docs.perplexity.ai/docs/getting-started/integrations/mcp-server.md) v1.0.0 moves its model-backed tools from the legacy Sonar models to [Agent API presets](https://docs.perplexity.ai/docs/agent-api/presets.md): `perplexity_ask` uses the `fast` preset, `perplexity_reason` uses `medium`, and `perplexity_research` uses `high`. Tool names and response shapes are unchanged, and all three tools are faster and cheaper on average than their Sonar predecessors. Long-running research now streams progress to MCP clients that request it, and cancelling an MCP request cancels the underlying run.

The `strip_thinking` and `reasoning_effort` parameters were removed from the tool schemas (the Agent API emits no think tags, and presets manage reasoning effort); clients still sending them are ignored gracefully.

**July 2026**

**Sonar Chat Completions migration**

More models, tools, and research-backed presets: Sonar Chat Completions is now [Agent API.](https://docs.perplexity.ai/docs/agent-api/quickstart.md) Migration guide [here](https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar/overview.md).

**July 2026**

**Agent API: New Models**

The Agent API added support for several new models this month, all with direct first-party token pricing. See the full list in the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

**Claude Opus 5**

The Agent API now supports `anthropic/claude-opus-5`.

**GPT-5.6 Family**

The Agent API now supports `openai/gpt-5.6-sol`, `openai/gpt-5.6-terra`, and `openai/gpt-5.6-luna`, giving you access to the latest GPT-5.6 models.

**Gemini Flash Models**

The Agent API now supports `google/gemini-3.6-flash` and `google/gemini-3.5-flash-lite`, adding Google's latest fast and cost-efficient models.

**Grok 4.5**

The Agent API now supports `xai/grok-4.5`, xAI's flagship coding and agentic model.

**Kimi K3**

The Agent API now supports `perplexity/kimi-k3`, Moonshot AI's flagship reasoning model. See the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md) for pricing and model-specific settings.

**Retired: Gemini 3.1 Flash Lite Preview**

`google/gemini-3.1-flash-lite-preview` has been retired: Google removed the underlying preview model from its API. Requests for this id now return a `model not supported` error. Use `google/gemini-3.1-flash-lite` instead — the stable successor at the same pricing. See the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

**June 2026**

**Agent API: New Models**

The Agent API expanded model coverage this month, all with direct first-party token pricing. See the full list in the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

* **Claude Sonnet 5** — `anthropic/claude-sonnet-5`, Anthropic's latest Sonnet model.
* **Kimi K2.7 Code** — `perplexity/kimi-k2.7-code`, Moonshot AI's coding and agentic model.
* **Nemotron 3 Super** — `nvidia/nemotron-3-super-120b-a12b`, NVIDIA's open-weight reasoning model.

**May 2026**

**Agent API: New Models**

The Agent API added support for several new third-party models this month, all with direct first-party token pricing. See the full list in the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

* **Claude Opus 4.8** — `anthropic/claude-opus-4-8`, Anthropic's flagship model.
* **Gemini 3.5 Flash** — `google/gemini-3.5-flash`, Google's fast multimodal model.
* **Gemini 3.1 Flash Lite** — `google/gemini-3.1-flash-lite` (and `-preview`), a cost-efficient option.
* **Grok 4.3** and the **Grok 4.20** family — `xai/grok-4.3`, `xai/grok-4.20-non-reasoning`, and `xai/grok-4.20-multi-agent`.

**May 2026**

**Finance Search: Now Available**

The `finance_search` tool is now available in the Agent API. Pull structured financial and market data — quotes, financials, earnings, analyst estimates, segment KPIs, ETF constituents, and more — for public companies and instruments. The model decides which fields to fetch based on your prompt, so a single call can return valuation, earnings, and context together.

**Highlights:**

* **Quotes and pricing**: Near-real-time prices, OHLCV ranges, pre-market and after-hours data
* **Financials**: Income statement, balance sheet, cash flow (quarterly and annual), key ratios
* **Earnings**: Last call transcript, filings, beat/miss history, guidance
* **Coverage and market activity**: Analyst estimates, top gainers/losers, ownership and corporate actions
* **Recommended configurations**: Presets for live quotes, single-company historical lookups, and multi-step cross-company research

Start here: [Finance Search](https://docs.perplexity.ai/docs/agent-api/tools/finance-search.md)

**April 2026**

**Agent API: New Third-Party Models**

The Agent API now supports Claude Opus 4.7, GPT-5.5, and Grok 4.20 Reasoning — extending model choice for tool-calling, structured outputs, and fallback chains. See the full list in the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

**API Key Management: Security Upgrade**

We've upgraded API key management with a one-time reveal model: full token values are now returned **only at the moment of creation** and cannot be retrieved again from the console or any endpoint. This significantly reduces the blast radius of credential exposure and aligns with industry best practices. Always set a descriptive `token_name` so keys remain identifiable after creation, and rotate regularly.

Start here: [API Key Management](https://docs.perplexity.ai/docs/admin/api-key-management.md)

**New Integration: n8n**

n8n now ships a native Perplexity node with full API coverage — Chat Completions, Agent, Search, and Embeddings — all configurable from the visual canvas. Models load dynamically from the API, so the dropdown always reflects the latest options.

Start here: [n8n Integration Guide](https://docs.perplexity.ai/docs/getting-started/integrations/n8n.md)

**New Integration: OpenClaw**

OpenClaw, the open-source terminal AI agent, now supports Perplexity Search API as a native web search provider. Configure your API key once and get structured search results (`title`, `url`, `snippet`) directly inside your terminal workflows.

Start here: [OpenClaw Integration Guide](https://docs.perplexity.ai/docs/getting-started/integrations/openclaw.md)

**API Credits now available through the AWS Marketplace**

The Perplexity API Platform is now available as a SaaS listing on AWS Marketplace. Purchase API credits through your AWS account for consolidated billing, simplified procurement, and no separate vendor relationship.

Start here: [AWS Marketplace](https://docs.perplexity.ai/docs/resources/aws-marketplace.md)

**`/v1/models` Endpoint**

A new `GET /v1/models` endpoint lists all available Agent API models in OpenAI-compatible format. No authentication required, useful for dynamic model selection in your integrations.

**March 2026**

**Agent API: New Third-Party Models**

The Agent API now supports additional third-party models including GPT-5.4, NVIDIA Nemotron, Claude Sonnet 4.6, and Gemini 3.1 Pro Preview — giving you more flexibility for tool-calling, structured outputs, and model fallback chains.

**Model Deprecations: Gemini 2.5 Flash & Gemini 2.5 Pro**

As of March 20, 2026, `google/gemini-2.5-flash` has been deprecated and removed from the API. `google/gemini-2.5-pro` followed on April 1, along with `google/gemini-3-pro-preview`. If you were using these models, we recommend switching to newer alternatives available in the [Agent API Models reference](https://docs.perplexity.ai/docs/agent-api/models.md).

**Agent API Endpoint: `/v1/agent`**

The canonical Agent API endpoint is now `/v1/agent`. The previous `/v1/responses` path continues to work as an alias for OpenAI compatibility, no migration is required.

**February 2026**

**Agent API: Now Available**

We're excited to announce the general availability of the **Agent API**! Build autonomous agents with production-ready guidance on model behavior, output controls, and OpenAI-compatibility patterns to seamlessly integrate with your existing systems.

Start here: [Agent API Quickstart](https://docs.perplexity.ai/docs/agent-api/quickstart.md)

**Embeddings API: Now Available**

We're thrilled to launch the **Embeddings API** with comprehensive guides for standard and contextualized embeddings, plus best practices for semantic search and retrieval workflows.

Start here: [Embeddings API Quickstart](https://docs.perplexity.ai/docs/embeddings/quickstart.md)

**December 2025**

**Model Deprecation: `sonar-reasoning` Removed**

As of December 15, 2025, the `sonar-reasoning` model has been deprecated and removed from the API. If you were using this model, we recommend migrating to `sonar-reasoning-pro` for enhanced multi-step reasoning capabilities with web search.

**New: Media Classifier for Intelligent Visual Content**

We're excited to introduce the **Media Classifier** — an intelligent system that automatically detects when your queries would benefit from visual content and includes relevant images or videos in responses.

**Key capabilities:**

* **Automatic detection**: Analyzes queries to identify when visual content adds value
* **Smart media selection**: Intelligently chooses between images, videos, or both based on query type
* **Context-aware**: Perfect for educational content, geographic queries, processes, and demonstrations
* **Configurable control**: Enable/disable and override media types as needed

Available exclusively with `sonar-pro`, the Media Classifier enhances responses for visual concepts, locations, step-by-step processes, and educational content.

**Search API Enhancements**

We've made several improvements to the Search API:

* **New `max_tokens` parameter**: Control the maximum tokens extracted per page in search results. This gives you finer control over response size and costs. [Learn more →](https://docs.perplexity.ai/docs/search/quickstart.md)
* **`last_updated_filter` support**: Filter search results by when content was last updated, in addition to publication date. Perfect for finding the most current information. [Learn more →](https://docs.perplexity.ai/docs/search/filters/date-time-filters.md)
* **Vercel AI SDK Support**: The Search API is now compatible with the Vercel AI SDK, allowing you to build with Perplexity in a framework-agnostic way. [Learn more →](https://ai-sdk.dev/tools-registry/perplexity-search)

**Ecosystem & Community**

New community showcase: [**Perplexity Client**](https://docs.perplexity.ai/docs/cookbook/showcase/perplexity-client.md) — An Electron-based desktop application with advanced API parameter controls, custom spaces, and API debugging mode. Built by the community for developers who want fine-grained control over their Sonar interactions.

**November 2025**

**Pro Search: Now Generally Available**

We're excited to announce the general availability of **Pro Search** for Sonar Pro! Pro Search enhances your queries with automated tool usage, enabling multi-step reasoning through intelligent tool orchestration.

**Key capabilities:**

* **Multi-step reasoning**: The model automatically performs multiple web searches and fetches URL content to answer complex queries
* **Real-time thought streaming**: Watch the model's reasoning process as it works through your question
* **Automatic classification**: Use `search_type: "auto"` to let the system intelligently route queries based on complexity
* **Built-in tools**: Access `web_search` and `fetch_url_content` tools that the model uses automatically

**MCP Server: One-Click Installation**

The [Perplexity MCP Server](https://docs.perplexity.ai/docs/getting-started/integrations/mcp-server.md) now supports **one-click installation** for popular AI development environments:

* **Cursor**: Click to auto-configure the Perplexity MCP server
* **VS Code**: One-click setup via the VS Code MCP extension
* **Claude Desktop & Claude Code**: Easy JSON configuration

The MCP server provides four powerful tools: `perplexity_search`, `perplexity_ask`, `perplexity_research`, and `perplexity_reason` — enabling AI assistants to access Perplexity's search and reasoning capabilities directly.

**October 2025**

**Official Perplexity SDKs**

We're thrilled to announce the official **Perplexity SDKs** for Python and Typescript! These SDKs provide convenient, type-safe access to all Perplexity APIs with both synchronous and asynchronous clients.

**Installation:**

```bash theme={null}
# Python
pip install perplexityai

# Typescript  
npm install @perplexity-ai/perplexity_ai
```

**Features:**

* Full type definitions for all request parameters and response fields
* Support for Sonar and Search APIs
* Streaming support with async iterators
* Automatic environment variable handling for API keys

Get started with our [SDK Quickstart Guide](https://docs.perplexity.ai/docs/sdk/overview.md).

**Interactive Search API Playground**

Test Search API queries and parameters in real time with our new [Interactive Playground](https://console.perplexity.ai) — **no API key required** to get started. Experiment with filtering options, see response structures, and refine your queries before implementing them in code.

**New Search API Capabilities**

* **`language_preference`**: Specify preferred languages for search results (available for `sonar` and `sonar-pro`)
* **`search_domain_filter`**: Filter results to specific domains for more targeted searches
* **Date/time filters**: Enhanced control over result freshness with publication and update filters
  **Ecosystem & Community**

New community showcase: [**StarPlex**](https://docs.perplexity.ai/docs/cookbook/showcase/starplex.md) — An AI-powered startup intelligence platform featuring an interactive 3D globe interface. Built with Sonar Pro, it helps entrepreneurs validate business ideas by mapping competitors, VCs, and market opportunities worldwide. Featured at recent hackathon events!

**September 2025**

**New: File Attachments Support**

You can now upload and analyze documents in multiple formats using Sonar models! This powerful new feature supports PDF, DOC, DOCX, TXT, and RTF files, allowing you to ask questions, extract information, and get summaries from your documents.

**Key capabilities:**

* **Document Analysis**: Ask questions about document content and get detailed answers
* **Content Extraction**: Pull out key information, data points, and insights
* **Multi-format Support**: Work with PDF, Word documents, text files, and Rich Text Format
* **Large Document Handling**: Process lengthy documents efficiently
* **Multi-language Support**: Analyze documents in various languages

Upload documents either via publicly accessible URLs using the `file_url` content type, similar to our existing image upload functionality.

**September 2025**

**New: Search-only API**

Introducing our standalone Search API that provides direct access to search results without LLM processing! This new endpoint gives you raw, ranked search results from Perplexity's continuously refreshed index.

**Perfect for:**

* Building custom search experiences
* Integrating search results into your own applications
* Creating specialized workflows that need search data without AI responses
* Applications requiring just the search functionality

**Key features:**

* Direct access to Perplexity's search index
* All existing search filters and controls
* Faster responses since no LLM processing is involved
* Same powerful filtering options (domain, date range, academic sources, etc.)

This complements our existing chat completions API and gives developers more flexibility in how they use Perplexity's search capabilities.

Learn more in our [Search API documentation](https://docs.perplexity.ai/docs/search/quickstart.md).

**September 2025**

**New: API Key Rotation Mechanism**

We've introduced a comprehensive API key rotation system to enhance security and simplify key management for your applications.

**Key features:**

* **Seamless Rotation**: Replace API keys without service interruption
* **Automated Workflows**: Set up automatic key rotation schedules
* **Enhanced Security**: Regularly refresh keys to minimize security risks
* **Audit Trail**: Track key usage and rotation history
* **Zero Downtime**: Smooth transitions between old and new keys

**How it works:**

1. Generate a new API key while keeping the old one active
2. Update your applications to use the new key
3. Deactivate the old key once migration is complete

This is particularly valuable for production environments where continuous availability is critical, and for organizations with strict security compliance requirements.

**Best practices:**

* Rotate keys every 30-90 days depending on your security requirements
* Use environment variables to manage keys in your applications
* Test key rotation in staging environments first
* Monitor key usage to ensure successful transitions

Access key rotation features through your [API Portal](https://console.perplexity.ai).

**August 2025**

**API model deprecation notice**

Please note that as of August 1, 2025, R1-1776 will be removed from the available models.

R1 has been a popular option for a while, but it hasn't kept pace with recent improvements and lacks support for newer features. To reduce engineering overhead and make room for more capable models, we're retiring it from the API.

If you liked R1's strengths, we recommend switching to `Sonar Pro Reasoning`. It offers similar behavior with stronger overall performance.

**July 2025**

**New: Detailed Cost Information in API Responses**

The API response JSON now includes detailed cost information for each request.

You'll now see a new structure like this in your response:

```json theme={null}
"usage": {
    "prompt_tokens": 8,
    "completion_tokens": 439,
    "total_tokens": 447,
    "search_context_size": "low",
    "cost": {
     "input_tokens_cost": 2.4e-05,
     "output_tokens_cost": 0.006585,
     "request_cost": 0.006,
     "total_cost": 0.012609
   }
}
```

**What's included:**

* **input\_tokens\_cost**: Cost attributed to input tokens
* **output\_tokens\_cost**: Cost attributed to output tokens
* **request\_cost**: Fixed cost per request
* **total\_cost**: The total cost for this API call

This update enables easier tracking of usage and billing directly from each API response, giving you complete transparency into the costs associated with each request.

**July 2025**

**New: SEC Filings Filter for Financial Research**

We're excited to announce the release of our new SEC filings filter feature, allowing you to search specifically within SEC regulatory documents and filings. By setting `search_domain: "sec"` in your API requests, you can now focus your searches on official SEC documents, including 10-K reports, 10-Q quarterly reports, 8-K current reports, and other regulatory filings.

This feature is particularly valuable for:

* Financial analysts researching company fundamentals
* Investment professionals conducting due diligence
* Compliance officers tracking regulatory changes
* Anyone requiring authoritative financial information directly from official sources

The SEC filter works seamlessly with other search parameters like date filters and search context size, giving you precise control over your financial research queries.

**Example:**

```bash theme={null}
curl --request POST \
  --url https://api.perplexity.ai/v1/sonar \
  --header 'accept: application/json' \
  --header 'authorization: Bearer $PERPLEXITY_API_KEY' \
  --header 'content-type: application/json' \
  --data '{
    "model": "sonar-pro",
    "messages": [{"role": "user", "content": "What was Apple's revenue growth in their latest quarterly report?"}],
    "stream": false,
    "search_domain": "sec",
    "web_search_options": {"search_context_size": "medium"}
}' | jq
```

For detailed documentation and implementation examples, please see our [SEC Guide](https://docs.perplexity.ai/guides/sec-guide.md).

**June 2025**

**Enhanced: Date Range Filtering with Latest Updated Field**

We've enhanced our date range filtering capabilities with new fields that give you even more control over search results based on content freshness and updates.

**New fields available:**

* `latest_updated`: Filter results based on when the webpage was last modified or updated
* `published_after`: Filter by original publication date (existing)
* `published_before`: Filter by original publication date (existing)

The `latest_updated` field is particularly useful for:

* Finding the most current version of frequently updated content
* Ensuring you're working with the latest data from news sites, blogs, and documentation
* Tracking changes and updates to specific web resources over time

**Example:**

```bash theme={null}
curl --request POST \
  --url https://api.perplexity.ai/v1/sonar \
  --header 'accept: application/json' \
  --header 'authorization: Bearer $PERPLEXITY_API_KEY' \
  --header 'content-type: application/json' \
  --data '{
    "model": "sonar-pro",
    "messages": [{"role": "user", "content": "What are the latest developments in AI research?"}],
    "stream": false,
    "web_search_options": {
      "latest_updated": "2025-06-01",
      "search_context_size": "medium"
    }
}'
```

For comprehensive documentation and more examples, please see our [Date Range Filter Guide](https://docs.perplexity.ai/guides/date-range-filter-guide.md).

**June 2025**

**New: Academic Filter for Scholarly Research**
We're excited to announce the release of our new academic filter feature, allowing you to tailor your searches specifically to academic and scholarly sources. By setting `search_mode: "academic"` in your API requests, you can now prioritize results from peer-reviewed papers, journal articles, and research publications.

This feature is particularly valuable for:

* Students and researchers working on academic papers
* Professionals requiring scientifically accurate information
* Anyone seeking research-based answers instead of general web content

The academic filter works seamlessly with other search parameters like `search_context_size` and date filters, giving you precise control over your research queries.

**Example:**

```bash theme={null}
curl --request POST \
  --url https://api.perplexity.ai/v1/sonar \
  --header 'accept: application/json' \
  --header 'authorization: Bearer $PERPLEXITY_API_KEY' \
  --header 'content-type: application/json' \
  --data '{
    "model": "sonar-pro",
    "messages": [{"role": "user", "content": "What is the scientific name of the lions mane mushroom?"}],
    "stream": false,
    "search_mode": "academic",
    "web_search_options": {"search_context_size": "low"}
}'
```

For detailed documentation and implementation examples, please see our [Academic Filter Guide](https://docs.perplexity.ai/guides/academic-filter-guide.md).

**May 2025**

**New: Reasoning Effort Parameter for Sonar Deep Research**

We're excited to announce our new reasoning effort feature for sonar-deep-research. This lets you control how much computational effort the AI dedicates to each query. You can choose from "low", "medium", or "high" to get faster, simpler answers or deeper, more thorough responses.

This feature has a direct impact on the amount of reasoning tokens consumed for each query, giving you the ability to control costs while balancing between speed and thoroughness.

**Options:**

* `"low"`: Faster, simpler answers with reduced token usage
* `"medium"`: Balanced approach (default)
* `"high"`: Deeper, more thorough responses with increased token usage

**Example:**

```bash theme={null}
curl --request POST \
  --url https://api.perplexity.ai/v1/sonar \
  --header 'accept: application/json' \
  --header 'authorization: Bearer ${PPLX_KEY}' \
  --header 'content-type: application/json' \
  --data '{
    "model": "sonar-deep-research",
    "messages": [{"role": "user", "content": "What should I know before markets open today?"}],
    "stream": true,
    "reasoning_effort": "low"
  }'
```

**May 2025**

**New: Asynchronous API for Sonar Deep Research**

We're excited to announce the addition of an asynchronous API for Sonar Deep Research, designed specifically for research-intensive tasks that may take longer to process.

This new API allows you to submit requests and retrieve results later, making it ideal for complex research queries that require extensive processing time.

The asynchronous API endpoints include:

1. `GET https://api.perplexity.ai/v1/async/sonar` - Lists all asynchronous chat completion requests for the authenticated user
2. `POST https://api.perplexity.ai/v1/async/sonar` - Creates an asynchronous chat completion job
3. `GET https://api.perplexity.ai/v1/async/sonar/{request_id}` - Retrieves the status and result of a specific asynchronous chat completion job

**Note:** Async requests have a time-to-live (TTL) of 7 days. After this period, the request and its results will no longer be accessible.

**May 2025**

**Enhanced API Responses with Search Results**

We've improved our API responses to give you more visibility into search data by adding a new `search_results` field to the JSON response object.

This enhancement provides direct access to the search results used by our models, giving you more transparency and control over the information being used to generate responses.

The `search_results` field includes:

* `title`: The title of the search result page
* `url`: The URL of the search result
* `date`: The publication date of the content

**Example:**

```json theme={null}
"search_results": [
  {
    "title": "Understanding Large Language Models",
    "url": "https://example.com/llm-article",
    "date": "2023-12-25"
  },
  {
    "title": "Advances in AI Research",
    "url": "https://example.com/ai-research",
    "date": "2024-03-15"
  }
]
```

This update makes it easier to:

* Verify the sources used in generating responses
* Create custom citation formats for your applications
* Filter or prioritize certain sources based on your needs

**Update: The `citations` field has been fully deprecated and removed.** All applications should now use the `search_results` field, which provides more detailed information including titles, URLs, and publication dates.

The `search_results` field is available across all our search-enabled models and offers enhanced source tracking capabilities.

**April 2025**

**New API Portal for Organization Management**

We are excited to announce the release of our new API portal, designed to help you better manage your organization and API usage.

With this portal, you can:

* Organize and manage your API keys more effectively.
* Gain insights into your API usage and team activity.
* Streamline collaboration within your organization.

Check it out here:\
[https://console.perplexity.ai](https://console.perplexity.ai)

**April 2025**

**New: Location filtering in search**

Looking to narrow down your search results based on users' locations?\
We now support user location filtering, allowing you to retrieve results only from a particular user location.

Check out the [guide](https://docs.perplexity.ai/guides/user-location-filter-guide.md).

**April 2025**

**Image uploads now available for all users!**

You can now upload images to Sonar and use them as part of your multimodal search experience.\
Give it a try by following our image upload guide:\
[https://docs.perplexity.ai/guides/image-attachments](https://docs.perplexity.ai/guides/image-attachments.md)

**April 2025**

**New: Date range filtering in search**

Looking to narrow down your search results to specific dates?\
We now support date range filtering, allowing you to retrieve results only from a particular timeframe.

Check out the guide:\
[https://docs.perplexity.ai/guides/date-range-filter-guide](https://docs.perplexity.ai/guides/date-range-filter-guide.md)

**April 2025**

**Clarified: Search context pricing update**

We've fully transitioned to our new pricing model: citation tokens are no longer charged.\
If you were already using the `search_context_size` parameter, you've been on this model already.

This change makes pricing simpler and cheaper for everyone — with no downside.

View the updated pricing:\
[https://docs.perplexity.ai/guides/pricing](https://docs.perplexity.ai/guides/pricing.md)

**April 2025**

**All features now available to everyone**

We've removed all feature gating based on tiered spending. These were previously only available to users of Tier 3 and above.

That means **every user now has access to all API capabilities**, regardless of usage volume or spend. Rate limits are still applicable.\
Whether you're just getting started or scaling up, you get the full power of Sonar out of the box.

**March 2025**

**Structured Outputs Available for All Users**

We're excited to announce that structured outputs are now available to all Perplexity API users, regardless of tier level. Based on valuable feedback from our developer community, we've removed the previous Tier 3 requirement for this feature.

**What's available now:**

* JSON structured outputs are supported across all models

This change allows developers to create more reliable and consistent applications from day one. We believe in empowering our community with the tools they need to succeed, and we're committed to continuing to improve accessibility to our advanced features.

Thank you for your feedback—it helps us make Perplexity API better for everyone.

**March 2025**

**Improved Sonar Models: New Search Modes**

We're excited to announce significant improvements to our Sonar models that deliver superior performance at lower costs. Our latest benchmark testing confirms that Sonar and Sonar Pro now outperform leading competitors while maintaining more affordable pricing.

Key updates include:

* **Three new search modes** across most Sonar models:
  * High: Maximum depth for complex queries
  * Medium: Balanced approach for moderate complexity
  * Low: Cost-efficient for straightforward queries (equivalent to current pricing)

* **Simplified billing structure**:
  * Transparent pricing for input/output tokens
  * No charges for citation tokens in responses (except for Sonar Deep Research)

The current billing structure will be supported as the default option for 30 days (until April 18, 2025). During this period, the new search modes will be available as opt-in features.

**Important Note:** After April 18, 2025, Sonar Pro and Sonar Reasoning Pro will not return Citation tokens or number of search results in the usage field in the API response.

**January 2025**

**API model deprecation notice**

Please note that as of February 22, 2025, several models and model name aliases will no longer be accessible. The following model names will no longer be available via API:

`llama-3.1-sonar-small-128k-online`

`llama-3.1-sonar-large-128k-online`

`llama-3.1-sonar-huge-128k-online`

We recommend updating your applications to use our recently released Sonar or Sonar Pro models – you can learn more about them here. Thank you for being a Perplexity API user.

**January 2025**

**Build with Perplexity's new APIs**

We are expanding API offerings with the most efficient and cost-effective search solutions available:  **Sonar** and **Sonar Pro**.

**Sonar** gives you fast, straightforward answers

**Sonar Pro** tackles complex questions that need deeper research and provides more sources

Both models offer built-in citations, automated scaling of rate limits, and public access to advanced features like structured outputs and search domain filters. And don't worry, we never train on your data. Your information stays yours.

You can learn more about our new APIs here - [https://docs.perplexity.ai](https://docs.perplexity.ai)

**November 2024**

**Citations Public Release and Increased Default Rate Limits**

We are excited to announce the public availability of citations in the Perplexity API. In addition, we have also increased our default rate limit for the sonar online models to 50 requests/min for all users.

Effective immediately, all API users will see citations returned as part of their requests by default. This is not a breaking change. The **return\_citations** parameter will no longer have any effect.

For bug reports or enterprise inquiries, please reach out to our team at [api@perplexity.ai](mailto:api@perplexity.ai)

**July 2024**

**Introducing New and Improved Sonar Models**

We are excited to announce the launch of our latest Perplexity Sonar models:

**Online Models** -
`llama-3.1-sonar-small-128k-online`
`llama-3.1-sonar-large-128k-online`

**Chat Models** -
`llama-3.1-sonar-small-128k-chat`
`llama-3.1-sonar-large-128k-chat`

These new additions surpass the performance of the previous iteration. For detailed information on our supported models, please visit our model card documentation.

**\[Action Required]** Model Deprecation Notice
Please note that several models will no longer be accessible effective 8/12/2024. We recommend updating your applications to use models in the Llama-3.1 family immediately.

The following model names will no longer be available via API -
`llama-3-sonar-small-32k-online`
`llama-3-sonar-large-32k-online`
`llama-3-sonar-small-32k-chat`
`llama-3-sonar-large-32k-chat`
`llama-3-8b-instruct`
`llama-3-70b-instruct`
`mistral-7b-instruct`
`mixtral-8x7b-instruct`

We recommend switching to models in the Llama-3.1 family:

**Online Models** -
`llama-3.1-sonar-small-128k-online`
`llama-3.1-sonar-large-128k-online`

**Chat Models** -
`llama-3.1-sonar-small-128k-chat`
`llama-3.1-sonar-large-128k-chat`

**Instruct Models** -
`llama-3.1-70b-instruct`
`llama-3.1-8b-instruct`

If you have any questions, please email [support@perplexity.ai](mailto:support@perplexity.ai).
Thank you for being a Perplexity API user.

Stay curious,

Team Perplexity

***

**April 2024**

**Model Deprecation Notice**

Please note that as of May 14, several models and model name aliases will no longer be accessible. We recommend updating your applications to use models in the Llama-3 family immediately. The following model names will no longer be available via API:

`codellama-70b-instruct`
`mistral-7b-instruct`
`mixtral-8x22b-instruct`
`pplx-7b-chat`
`pplx-7b-online`
