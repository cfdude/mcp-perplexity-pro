# Proposal

## Why

Live use of the 2.0.0 server in another project (2026-10-13, 12 billed calls, $0.036) found three defects in what ask, chat and research return, all confirmed against our own captured fixtures:

- **A. Cited ids missing from `sources`.** A medium research answer cited `[web:71]`, `[web:65]`, `[web:79]` and `[web:125]`, none of which was in `sources`. Cause: `agent._sources` de-duplicates by URL and keeps only the first result's `id`. In a multi-search run the same URL comes back under several ids (fixture `agent_background_cancelled.json`: `crates.io/crates/rs-stats` is ids 10 and 71, `scirs2-stats` is 9 and 68), and the answer may cite any of them. The marker number equals the search result `id` (fixture `agent_background_completed.json`: `[web:1]`, `[web:11]`, `[web:21]` are results with ids 1, 11 and 21). The README and `design.md` claim the markers are not numbered like the ids: that is wrong for search markers.
- **B. Medium research documented as cheaper and faster than seen.** The docs say about 35 to 40 s and $0.016 to $0.017 for medium; that rests on two runs of one narrow query. The other project saw about 90 s and $0.023. Cost follows how many fetches and searches the run makes (fixture: $0.01352 of tool cost, $0.01052 of it from 3 `fetch_url` calls).
- **C. Citation markers inside structured answers.** With `json_schema`, string values can end in `[1][3]`, which breaks exact-value parsing. The API offers no option to suppress them (local docs and the recorded request set show none).

## What Changes

- `sources` entries gain `ids`: every result id the run gave that URL, in first-seen order. `id` stays the first of them, so stored research jobs (which hold only `id`) still read, with `ids` empty.
- The readable result (ask, `perplexity_jobs` result) shows `ids` beside each source, so a text-only client can find what `[web:71]` cites.
- `answer_json` string values lose a trailing run of citation markers (`[3]` and `[web:12]` forms only, ids bounded to three ASCII digits, any number of them, with the whitespace before them; scanned from the end in linear time and never raising); the raw `answer` text is returned unchanged and a warning says how many markers were removed. Keys and non-trailing text are never touched.
- The README, the `design.md` of the archived `py-agent-api` (note only) and the ask, chat and research descriptions are corrected: markers `[N]` and `[web:N]` name the search result whose `id` is `N` (checked against the fixtures), a fetched page has no id and so cannot be matched, and medium research is stated as `$0.016 to $0.023` and `35 to 90 s` over three runs, query-dependent.
- Add to the README the lesson from the same report: `fast` answers sound sure on thin evidence; use `medium` or `perplexity_research` for anything that feeds a deep analysis. (README only, so `tools/list` does not grow.)
- Out of scope: rewriting or removing markers in the plain `answer`, mapping markers to sources in the answer text, changing what is recorded or billed, any API option for citations.

## Capabilities

### Modified Capabilities

- `agent-ask`: "Sources" (all ids per URL, the markers' numbering stated as verified for search results) and "Structured output" (trailing markers removed from string values of `answer_json`). Research and chat results share the `Source` model, so they follow; their specs name no id behaviour.

## Impact

- **Code:** `agent.py` (`Source`, `_sources`, a marker cleaner used by `digest`), the research and jobs tool result text where sources are rendered (`tools/jobs.py` and `tools/ask.py` text rendering), `README.md`, tool docstrings (`ask`, `chat`, `research`), `CLAUDE.md` (module row note), `CHANGELOG.md`.
- **Tests (existing files edited):** the source and digest tests, the research result tests, the pinned-schema tests that name `Source` fields.
- **Dependencies, migration, settings:** none (stored `sources_json` is read tolerantly).
- **Spend:** none for the change; live acceptance is one medium research and one structured ask, well under $0.10.
