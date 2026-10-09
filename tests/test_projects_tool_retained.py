"""Task 4.1: ``perplexity_projects`` and retained records (local-storage "Deleting a project
keeps retained records", "Project management tool"), driven through a real MCP client call."""

import httpx2
import jsonschema
import pytest
from fastmcp import Client
from sqlalchemy import text
from test_storage_uow import write_note

from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.usage import record_usage

TOOL = "perplexity_projects"


@pytest.fixture
async def server(make_settings, storage_engine):
    def no_upstream(request):
        raise AssertionError("perplexity_projects must not call the upstream API")

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(no_upstream))
    yield build_server(make_settings(), http, storage_engine)
    await http.aclose()


async def call(server, **arguments):
    async with Client(server) as client:
        return await client.call_tool(TOOL, arguments, raise_on_error=False)


async def scalar(engine, sql):
    async with engine.connect() as conn:
        return (await conn.execute(text(sql))).scalar_one()


async def spend(engine, project, count):
    for n in range(count):
        assert await record_usage(
            engine, tool="t", api="agent", project=project, request_id=f"{project}-{n}"
        )


async def test_delete_removes_ordinary_rows_and_keeps_spend_history(server, storage_engine):
    await write_note(storage_engine, "a", "alpha")
    await write_note(storage_engine, "b", "alpha")
    await spend(storage_engine, "alpha", 3)
    result = await call(server, action="delete", project="alpha", confirm=True)
    assert not result.is_error
    assert result.structured_content["rows_removed"] == 2
    assert result.structured_content["rows_retained"] == 3
    assert await scalar(storage_engine, "SELECT count(*) FROM notes") == 0
    assert await scalar(storage_engine, "SELECT count(*) FROM usage_events") == 3
    assert (
        await scalar(
            storage_engine,
            "SELECT count(*) FROM usage_events WHERE project_id IS NULL AND project_name = 'alpha'",
        )
        == 3
    )
    listed = await call(server, action="list")
    assert listed.structured_content["projects"] == []  # the project itself is gone
    assert listed.structured_content["rows_retained"] is None


async def test_the_rendered_text_names_both_counts_and_says_spend_is_kept(server, storage_engine):
    await write_note(storage_engine, "a", "alpha")
    await write_note(storage_engine, "b", "alpha")
    await spend(storage_engine, "alpha", 3)
    result = await call(server, action="delete", project="alpha", confirm=True)
    rendered = result.content[0].text
    assert "alpha" in rendered
    assert "2 row(s) removed" in rendered
    assert "3 retained record(s)" in rendered
    assert "spend history" in rendered.lower()


async def test_default_with_only_spend_history_is_deletable_and_recreated(server, storage_engine):
    await write_note(storage_engine, "n")  # creates the project first: recording never does
    await spend(storage_engine, "default", 1)
    result = await call(server, action="delete", project="default", confirm=True)
    assert result.structured_content["rows_removed"] == 1
    assert result.structured_content["rows_retained"] == 1
    assert await write_note(storage_engine, "again") == "default"
    assert await scalar(storage_engine, "SELECT count(*) FROM usage_events") == 1
    assert (
        await scalar(storage_engine, "SELECT count(*) FROM usage_events WHERE project_id IS NULL")
        == 1
    )


async def test_the_description_and_confirmation_say_spend_history_is_kept(server):
    async with Client(server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
    assert "everything stored in it" not in tool.description
    assert "spend history" in tool.description.lower()
    assert "kept" in tool.description.lower()
    refused = await call(server, action="delete", project="alpha")
    message = refused.structured_content["message"]
    assert refused.structured_content["category"] == "confirmation_required"
    assert "removes all its data" not in message and "spend history" in message.lower()


async def test_structured_content_validates_against_the_advertised_schema(server, storage_engine):
    await write_note(storage_engine, "a", "alpha")
    await spend(storage_engine, "alpha", 2)
    async with Client(server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
        schema = tool.output_schema
        assert schema["properties"]["rows_retained"]["description"]
        listed = await client.call_tool(TOOL, {"action": "list"})
        jsonschema.validate(listed.structured_content, schema)
        deleted = await client.call_tool(
            TOOL, {"action": "delete", "project": "alpha", "confirm": True}
        )
        jsonschema.validate(deleted.structured_content, schema)
        assert deleted.structured_content["rows_retained"] == 2
