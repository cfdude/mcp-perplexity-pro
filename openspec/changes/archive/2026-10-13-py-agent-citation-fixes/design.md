## Context

`agent._sources` builds `sources` from `output[].search_results.results[]` and `fetch_url_results.contents[]`, de-duplicating by URL and keeping the first row's `id`. Evidence gathered 2026-10-13 from the committed fixtures (no new API calls): the marker number in the answer equals a search result's `id`; one URL can carry several ids in one run; fetched pages carry no id; `annotations` is `[]` in every capture; the one structured fixture returns clean JSON (trivial schema), so C is reported by a user and not reproduced in our fixtures.

## Goals / Non-Goals

**Goals:** every id a marker can cite finds its source; structured values parse without trailing markers; the docs say what the fixtures show.
**Non-Goals:** rewriting the answer text, inserting source numbers, any request option (none exists), changing billing, a migration.

## Decisions

**D1. Add `ids`, keep `id`.** `Source.ids: list[int]` holds every distinct integer id for the URL in first-seen order; `id` is `ids[0]` or null. Stored `research_jobs.sources_json` rows hold the old shape; `Source` defaults `ids` to `[]`, so reading them needs no migration and nothing is rewritten. Alternative rejected: one source entry per `(id, url)` (the list would repeat pages and break "each URL once", which existing tests and callers rely on). Alternative rejected: replacing `id` by `ids` (breaks stored rows and every reader for no gain).

**D2. A fetched page's id stays null, and the cleaner does not care what a marker maps to.** Fixtures show fetch rows with no `id`, and the one fetch-only sample cites `[web:0]`; a single sample does not establish 0-based indexing, so the spec says markers cannot be matched to fetched pages and the docs say "unverified" for that case.

**D3. Marker removal is narrow on purpose.** A marker is `[N]` (ASCII digits, 1 to 999, no leading zero) or `[web:N]` (ASCII digits, 0 to 999): bounded so `[2024]`, `[0]` and ids that are really data survive, ASCII-only so Unicode digits and spaces are never touched. The cleaner scans each string leaf **from its end** (strip trailing ASCII whitespace, then peel `]`-terminated markers by looking back at most 12 characters for `[`), so its time is linear and never a backtracking search (a regex such as `(\s*\[..\])+\s*$` is quadratic on long whitespace runs). It walks dicts and lists iteratively with an explicit stack (keys never touched) and is wrapped so that any failure returns the uncleaned value plus a warning: `digest` is total by contract and a billed answer must never be lost to the cleaner. A bare marker glued to text (`x[1]`) is removed, because that is how the API writes most markers; the cost is that a value genuinely ending in `[1]` is trimmed, which the warning reveals. A marker in the middle of a string stays: a value such as `"array [1] index"` may be legitimate. Removal happens after `json.loads`, never on the raw text, so the answer text still equals what the API sent and the warning counts markers removed (the count is part of the contract so the caller can tell cleaning happened). Alternative rejected: ask the model not to cite through injected instructions (it changes the user's prompt silently and the API gives no guarantee).

**D4. Render the ids.** `tools/ask.py:72-78` and `tools/jobs.py:275-279` number sources by list position; a text-only client would read `[web:71]` as list item 71. Each rendered line gains `(ids 10, 71)` when `ids` is non-empty. Chat has no text render of sources (its structured result carries them), so nothing to change there.

**D5. Time and cost docs.** State the range from all runs we have (three: $0.01599, $0.01722 and the reported $0.023, 35 to about 90 s), say it is query-dependent and name the cost driver (fetch and search invocations; fixture tool cost $0.01352, $0.01052 from three `fetch_url` calls). No estimate for unmeasured depths changes.

## Risks / Trade-offs

- A legitimate value ending in `[1]` is trimmed (a value that is only a marker becomes an empty string). Mitigation: the warning names the count, the raw text is intact, and the removal is limited to trailing runs.
- `ids` lists are unbounded in principle; a run returns on the order of hundreds of results, so the bound is the response size already held in memory.
- C is a user report not yet reproduced in a fixture: the acceptance task makes one live structured ask with a schema that invites a citation and records the outcome either way.

## Migration Plan

None. Stored sources keep working; new observations store `ids`.

## Open Questions

None.
