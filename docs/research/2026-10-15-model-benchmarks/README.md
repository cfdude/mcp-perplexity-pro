# Model benchmark research and effort probe, 2026-10-15

Evidence for the `model-matrix` and `routing-v2` epics. Nothing here is verified by us beyond the
effort probe; read it as a draft to be checked, not a source of truth.

## Perplexity Research (five runs, one per provider family)
- Tool: `perplexity-pro research --depth medium`, prompt in `prompt.txt` (benchmarks, dates, source
  URLs, independent versus vendor-reported, modalities, documented effort levels; "no published
  data" instead of guesses). Answers: `anthropic.md`, `openai.md`, `google.md`, `xai.md`,
  `perplexity.md`. Total cost $0.367 (anthropic $0.027, openai $0.064, google $0.120, xai $0.059,
  perplexity $0.097), each run a few minutes.
- All 54 live models (`GET /v1/models` on 2026-10-15) got a row; 53 have at least one scored
  benchmark, `xai/grok-4.20-multi-agent` has none.
- Benchmarks that recur (rows with a score): GPQA 40, Terminal-Bench 32, MMLU-Pro 25, SWE-bench
  Verified 24, MMMU 22, LiveCodeBench 16, AIME 11, SWE-bench Pro 10, BrowseComp 9, Humanity's Last
  Exam 5. Different vendors lead with different coding benchmarks (Verified, Pro, DeepSWE), so a
  coding comparison across vendors needs a common benchmark; many pairs have none.
- The run labelled 147 numbers independent and 40 vendor-reported; most cited links are vals.ai
  (65), vendor docs and release pages, epoch.ai (21), openrouter.ai, with a tail of aggregator
  blogs. The labels are the research model's, not ours.
- Documented effort levels appear for 28 rows; they come from vendor docs and need not match what
  Perplexity's gateway accepts (see the probe).

## Effort probe (`effort-probe.json`)
54 calls, "Reply with the single word OK.", `max_output_tokens` 300, no tools, 9 models x
(none, low, medium, high, xhigh, bogus); cost $0.01.
- All 9 accepted none, low, medium and high; 8 of 9 accepted xhigh; `openai/gpt-5-nano` answered
  400 to `xhigh`. `bogus` is refused with "effort must be one of: none minimal low medium high".
- Reasoning tokens or cost changed with effort for `gpt-5-nano`, `gemini-3.5-flash` and `gpt-6-sol`
  only; the Claude models, `sonar` and `grok-4.5` accepted every level with no visible change on
  this trivial prompt (inconclusive: a hard prompt is needed to see an effect).
- Perplexity's docs page (`docs.perplexity.ai/docs/agent-api/models`) lists 40 of the 54 live models
  and names the presets' model `gpt-5.6-luna` where live calls report `gpt-6-luna`; it has no
  per-model capability table (one note: Kimi K3 accepts `max`; Nemotron 3.5 Super is text only).
