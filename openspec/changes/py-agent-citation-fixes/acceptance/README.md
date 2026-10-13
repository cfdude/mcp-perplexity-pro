# Acceptance: py-agent-citation-fixes (live, 2026-10-13, pm2 restarted at 60f90ab)

Throwaway project `acceptance-citations` (deleted afterwards; spend history kept).

## Medium research (job 4), question: published pricing of Pinecone, Weaviate, Qdrant, Zilliz, Chroma
- Started 13:58:38Z, finished 13:59:49Z: **71 s**. Cost reported **$0.02524** (58588 input, 3398 output tokens); 7 searches, 5 fetches.
- Markers cited in the answer: `[web:1] [web:34] [web:47] [web:46] [web:16] [web:62] [web:20] [web:18]`.
- Every cited number is in some source's `ids`: 1, 34 (weaviate.io/pricing), 47 (`ids` [47, 73], qdrant.tech/pricing), 46 ([46, 74]), 16 ([16, 62], zilliz.com/pricing), 62 (the same Zilliz source), 20 ([20, 61]), 18 ([18, 60]). **8 of 8 cited ids resolve.** Before this change, ids 62, 73-79 and the other repeats were dropped by the URL de-duplication, which is the reported defect.
- 12 URLs came back under two ids; all are kept in `ids`.

## Structured ask (fast preset, `json_schema` for `releases[{version, released}]`, prompt asks for inline citations)
- Cost $0.00168, 2118 ms, answer_json clean, no warning. The model returned no citation markers with this schema, so defect C was **not reproduced** live here; the cleaner is covered by the unit tests (fixtures cannot invite it). Sources show `ids`.

## Spend reconciliation (`perplexity_usage`, project `acceptance-citations`)
- 2 calls, 0 errors, 0 unknown cost: research 25240000 + ask 1680000 = **26920000 nano-USD = $0.02692**, equal to the sum of the results' `cost_usd` to the nano-USD. The provider console was not read (waived by Rob on 2026-10-11).

## Medium research time and cost, all measured runs
$0.01599 (fixture), $0.01722 and 39 s (2026-10-09 acceptance), $0.02524 and 71 s (this run); another project reported about $0.023 and 90 s. Range stated in the docs: $0.016 to $0.025, 35 to 90 s (four runs).

## tools/list size
One `tools/list` POST to the restarted server (`wc -c`, 2026-10-13): **56898 bytes**, against 56161 at `aba65c1` (+737 bytes, +1.3%): the `ids` field in the shared `Source` model of ask, chat and jobs.
