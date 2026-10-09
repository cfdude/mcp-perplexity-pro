"""The configured API key inside caller or model content (query, message, title, answer, source
titles and URLs): content may hold key-SHAPED examples, but never the configured key itself
(server-runtime "Secrets are never emitted", as modified by py-agent-api, design D14)."""

import json

from agent_support import fixture
from chat_support import FIRST  # noqa: F401
from research_support import COMPLETED
from secrets_support import (
    ASK,
    CHAT,
    JOBS,
    KEY,
    OTHER,
    QUEUED,
    RESEARCH,
    completed_body,
    ok,
)


async def test_the_configured_key_inside_caller_or_model_content_is_removed_not_stored(keyed):
    """Content may hold key-SHAPED examples (above), but never the configured key itself: the
    modified "Secrets are never emitted" requirement bars it from every result and row."""
    run = await keyed()
    schema = {"type": "object", "properties": {"note": {"type": "string"}}}
    ask = await run(
        ASK,
        ok(
            completed_body(
                json.dumps({"note": f"key {KEY} and {OTHER}"}),
                title=f"Page {KEY}",
                url=f"https://example.com/{KEY}",
                rid="resp_ask",
            )
        ),
        query=f"my key is {KEY}",
        json_schema=schema,
    )
    sent = await run(
        CHAT,
        ok(completed_body(f"echo {KEY} {OTHER}", title="t", url="https://e.com/", rid="resp_c")),
        action="send",
        message=f"use {KEY} and {OTHER}",
        title=f"Title {KEY}",
    )
    read = await run(CHAT, action="read", chat_id=1)
    await run(RESEARCH, ok(fixture(QUEUED)), query=f"research {KEY} then {OTHER}")
    snapshot = fixture(COMPLETED)
    for item in snapshot["output"]:
        if item["type"] == "message":
            item["content"][-1]["text"] = f"found {KEY}"
    await run(JOBS, ok(snapshot), action="status", job_id=1)
    done = await run(JOBS, action="result", job_id=1)
    listed = await run(JOBS, action="list")

    assert ask.structured_content["answer_json"] == {"note": f"key [redacted] and {OTHER}"}
    assert ask.structured_content["sources"][0]["title"] == "Page [redacted]"
    assert ask.structured_content["sources"][0]["url"] == "https://example.com/[redacted]"
    assert sent.structured_content["answer"] == f"echo [redacted] {OTHER}"
    assert [m["content"] for m in read.structured_content["messages"]] == [
        f"use [redacted] and {OTHER}",
        f"echo [redacted] {OTHER}",
    ]
    assert read.structured_content["chat"]["title"] == "Title [redacted]"
    assert done.structured_content["answer"] == "found [redacted]"
    assert listed.structured_content["jobs"][0]["query_excerpt"] == (
        f"research [redacted] then {OTHER}"
    )
    for text in run.texts():
        assert KEY not in text
    for table, column, value in await run.cells():
        assert KEY not in value, (table, column)
    assert KEY not in run.log_text() and KEY.encode() not in run.database_bytes()
