"""Task 7.2: the ``perplexity_projects`` tool (local-storage 'Project management tool' and
'Project deletion outcomes'), driven through a real MCP client call.

The child table ``notes`` (ON DELETE CASCADE from ``projects``) comes from the test-only
``storage_engine`` fixture and stands in for the project-scoped tables later changes add; the
tool must count and delete its rows without being edited.
"""

from datetime import datetime

import httpx2
import jsonschema
import pytest
from fastmcp import Client
from sqlalchemy import text
from test_storage_uow import write_note

from mcp_perplexity_pro.server import build_server
from mcp_perplexity_pro.storage.projects import get_or_create_project
from mcp_perplexity_pro.storage.session import unit_of_work

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


async def scalar(engine, sql, **params):
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar_one()


async def names(engine):
    async with engine.connect() as conn:
        return sorted((await conn.execute(text("SELECT name FROM projects"))).scalars())


# --- Listing -----------------------------------------------------------------------------


async def test_listing_returns_names_with_creation_times(server, storage_engine):
    await write_note(storage_engine, "a", "alpha")
    await write_note(storage_engine, "b", "beta")
    result = await call(server, action="list")
    assert not result.is_error
    listed = result.structured_content["projects"]
    assert [p["name"] for p in listed] == ["alpha", "beta"]
    for entry in listed:
        created = datetime.fromisoformat(entry["created_at"])
        assert created.tzinfo is not None  # UTC, so a client can compare it
        assert abs((datetime.now(created.tzinfo) - created).total_seconds()) < 300
    assert "alpha" in result.content[0].text and "beta" in result.content[0].text


async def test_list_creates_no_project_not_even_default(server, storage_engine):
    result = await call(server, action="list")
    assert result.structured_content["projects"] == []
    assert await names(storage_engine) == []


# --- Delete: confirmation and name rules --------------------------------------------------


@pytest.mark.parametrize("confirm", [None, False])
async def test_delete_without_confirm_removes_nothing(server, storage_engine, confirm):
    await write_note(storage_engine, "keep", "alpha")
    arguments = {"action": "delete", "project": "alpha"}
    if confirm is not None:
        arguments["confirm"] = confirm
    result = await call(server, **arguments)
    assert result.is_error
    assert result.structured_content["category"] == "confirmation_required"
    assert await names(storage_engine) == ["alpha"]
    assert await scalar(storage_engine, "SELECT count(*) FROM notes") == 1


async def test_delete_of_a_missing_project_is_not_found_and_creates_nothing(server, storage_engine):
    await write_note(storage_engine, "x", "alpha")
    result = await call(server, action="delete", project="ghost", confirm=True)
    assert result.is_error
    assert result.structured_content["category"] == "not_found"
    assert await names(storage_engine) == ["alpha"]  # no 'ghost', no 'default'


async def test_delete_with_a_path_like_name_is_invalid_request(server, storage_engine):
    result = await call(server, action="delete", project="../etc", confirm=True)
    assert result.is_error
    assert result.structured_content["category"] == "invalid_request"
    assert await names(storage_engine) == []


async def test_delete_with_a_key_shaped_name_is_invalid_request(server, storage_engine):
    name = "pplx-" + "abcdefghijklmnopqrstuvwx"
    result = await call(server, action="delete", project=name, confirm=True)
    assert result.structured_content["category"] == "invalid_request"
    assert name not in str(result.structured_content) and name not in result.content[0].text
    assert await names(storage_engine) == []


async def test_error_text_never_contains_the_configured_key(server, dummy_api_key):
    """The key can be typed as a project name (valid characters); the middleware redacts it."""
    result = await call(server, action="delete", project=dummy_api_key, confirm=True)
    assert result.is_error
    assert result.structured_content["category"] == "not_found"
    assert dummy_api_key not in str(result.structured_content)
    assert dummy_api_key not in result.content[0].text


async def test_delete_without_a_project_is_invalid_request(server):
    result = await call(server, action="delete", confirm=True)
    assert result.structured_content["category"] == "invalid_request"


async def test_unknown_action_is_invalid_request(server):
    result = await call(server, action="rename")
    assert result.structured_content["category"] == "invalid_request"


# --- Delete: the effect ---------------------------------------------------------------------


async def test_confirmed_delete_removes_child_rows_and_reports_the_count(server, storage_engine):
    for body in ("one", "two", "three"):
        await write_note(storage_engine, body, "alpha")
    await write_note(storage_engine, "other", "beta")
    result = await call(server, action="delete", project="alpha", confirm=True)
    assert not result.is_error
    assert result.structured_content["project"] == "alpha"
    assert result.structured_content["rows_removed"] == 3
    assert "alpha" in result.content[0].text and "3" in result.content[0].text
    assert await names(storage_engine) == ["beta"]
    assert await scalar(storage_engine, "SELECT count(*) FROM notes") == 1  # beta's note survives
    listed = await call(server, action="list")
    assert [p["name"] for p in listed.structured_content["projects"]] == ["beta"]


async def test_deleting_an_empty_project_reports_zero_rows(server, storage_engine):
    async with unit_of_work(storage_engine) as session:
        await get_or_create_project(session, "empty")
    result = await call(server, action="delete", project="empty", confirm=True)
    assert result.structured_content["rows_removed"] == 0
    assert await names(storage_engine) == []


async def test_default_can_be_deleted_and_is_recreated_on_next_use(server, storage_engine):
    await write_note(storage_engine, "first")
    assert await names(storage_engine) == ["default"]
    result = await call(server, action="delete", project="default", confirm=True)
    assert result.structured_content == {
        "action": "delete",
        "projects": None,
        "project": "default",
        "rows_removed": 1,
    }
    assert await names(storage_engine) == []
    assert await write_note(storage_engine, "second") == "default"  # get-or-create recreates it
    assert await names(storage_engine) == ["default"]
    assert await scalar(storage_engine, "SELECT count(*) FROM notes") == 1


# --- Generic over project-scoped tables ----------------------------------------------------


async def test_every_table_with_a_project_foreign_key_is_counted_and_cleared(
    server, storage_engine
):
    """A later epic's table (here: no cascade, different column name) needs no tool change."""
    async with storage_engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE runs (id INTEGER PRIMARY KEY, "
                "owner INTEGER NOT NULL REFERENCES projects(id))"
            )
        )
        await conn.execute(text("CREATE TABLE unrelated (id INTEGER PRIMARY KEY, n INTEGER)"))
        await conn.execute(text("INSERT INTO unrelated (n) VALUES (7)"))
    await write_note(storage_engine, "a", "alpha")
    await write_note(storage_engine, "b", "alpha")
    pid = await scalar(storage_engine, "SELECT id FROM projects WHERE name='alpha'")
    async with storage_engine.begin() as conn:
        await conn.execute(text("INSERT INTO runs (owner) VALUES (:p), (:p)"), {"p": pid})
    result = await call(server, action="delete", project="alpha", confirm=True)
    assert result.structured_content["rows_removed"] == 4  # 2 notes + 2 runs
    assert await scalar(storage_engine, "SELECT count(*) FROM runs") == 0
    assert await scalar(storage_engine, "SELECT count(*) FROM unrelated") == 1  # not scoped


async def test_delete_is_one_transaction(server, storage_engine):
    """A failure after the child rows are gone puts everything back."""
    await write_note(storage_engine, "a", "alpha")
    await write_note(storage_engine, "b", "alpha")
    async with storage_engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TRIGGER veto BEFORE DELETE ON projects "
                "BEGIN SELECT RAISE(ABORT, 'vetoed'); END"
            )
        )
    result = await call(server, action="delete", project="alpha", confirm=True)
    assert result.is_error
    assert result.structured_content["category"] == "internal_error"
    assert "vetoed" not in str(result.structured_content)
    assert await names(storage_engine) == ["alpha"]
    assert await scalar(storage_engine, "SELECT count(*) FROM notes") == 2


# --- Tool surface ----------------------------------------------------------------------------


async def test_tool_surface_and_structured_output_validate_against_the_schema(
    server, storage_engine
):
    await write_note(storage_engine, "a", "alpha")
    async with Client(server) as client:
        tool = next(t for t in await client.list_tools() if t.name == TOOL)
        props = tool.input_schema["properties"]
        assert set(props) == {"action", "project", "confirm"}
        assert tool.input_schema["required"] == ["action"]
        assert props["action"]["enum"] == ["list", "delete"]
        assert all(p.get("description") for p in props.values())
        assert tool.description
        assert tool.output_schema is not None
        listed = await client.call_tool(TOOL, {"action": "list"})
        jsonschema.validate(listed.structured_content, tool.output_schema)
        assert listed.structured_content["project"] is None
        deleted = await client.call_tool(
            TOOL, {"action": "delete", "project": "alpha", "confirm": True}
        )
        jsonschema.validate(deleted.structured_content, tool.output_schema)
        assert deleted.structured_content["rows_removed"] == 1
