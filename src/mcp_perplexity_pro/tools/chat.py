"""``perplexity_chat``: multi-turn conversations kept in the local database (agent-chat spec).

Local history is the truth and ``previous_response_id`` is a shortcut (design D6). A send makes
the upstream call through ``agent.run_costed`` (project committed first, no write unit open
across the call, usage recorded), and only then writes the chat in one short unit of work.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_perplexity_pro.agent import (
    DEFAULT_PROJECT,
    AskOptions,
    Source,
    UsageSummary,
    build_request,
    check_row_id,
    check_text,
    clean_text,
    digest,
    run_costed,
    shielded_write,
)
from mcp_perplexity_pro.client import is_response_id
from mcp_perplexity_pro.errors import PerplexityError
from mcp_perplexity_pro.redaction import scrub_secrets
from mcp_perplexity_pro.storage.chats import (
    AssistantTurn,
    ChatSummary,
    StoredMessage,
    append_turn,
    chat_history,
    chat_summary,
    create_chat,
    delete_chat,
    last_anchor,
    list_chats,
    load_chat,
    read_messages,
)
from mcp_perplexity_pro.storage.projects import find_project, validate_project_name
from mcp_perplexity_pro.storage.session import unit_of_work
from mcp_perplexity_pro.tools.ask import GENERIC_400, build_result, render_answer
from mcp_perplexity_pro.usage import failure_summary

logger = logging.getLogger(__name__)

TOOL = "perplexity_chat"
ACTIONS = ("send", "list", "read", "delete")
DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT = 20, 100
DEFAULT_READ_LIMIT, MAX_READ_LIMIT = 50, 200
MAX_TITLE_CHARS = 120
REPLAY_WARN_CHARS = 100_000  # stored text above this makes a replay worth a warning


class ChatInfo(BaseModel):
    id: Annotated[int, Field(description="The chat's id")]
    title: Annotated[str, Field(description="The chat's title")]
    message_count: Annotated[int, Field(description="Messages stored in the chat")]
    created_at: Annotated[datetime, Field(description="When the chat started (UTC)")]
    updated_at: Annotated[datetime, Field(description="When the chat last gained a turn (UTC)")]


class ChatMessageOut(BaseModel):
    id: Annotated[int, Field(description="The message's id")]
    role: Annotated[str, Field(description="user or assistant")]
    content: Annotated[str, Field(description="The message text")]
    created_at: Annotated[datetime, Field(description="When it was stored (UTC)")]
    response_id: Annotated[str | None, Field(description="The API response id (assistant)")] = None
    model: Annotated[str | None, Field(description="The model that answered (assistant)")] = None
    preset: Annotated[str | None, Field(description="The depth used (assistant)")] = None
    sources: Annotated[list[Source], Field(description="Sources the run touched (assistant)")] = []


class ChatResult(BaseModel):
    """The result of every action; the fields an action does not use are null (design D10)."""

    action: Annotated[str, Field(description="The action that ran")]
    project: Annotated[str, Field(description="The project the action ran in")]
    chat_id: Annotated[
        int | None,
        Field(
            description="The chat the action concerns (the new chat for a first send); null for "
            "list and for an incomplete or unsaved first send"
        ),
    ] = None
    chat: Annotated[ChatInfo | None, Field(description="That chat's record")] = None
    chats: Annotated[list[ChatInfo] | None, Field(description="Chats found (list only)")] = None
    messages: Annotated[
        list[ChatMessageOut] | None, Field(description="Messages in order (read only)")
    ] = None
    chats_total: Annotated[int | None, Field(description="All chats in the project (list)")] = None
    messages_total: Annotated[int | None, Field(description="All messages in the chat (read)")] = (
        None
    )
    truncated: Annotated[
        bool | None, Field(description="Whether limit cut the list or the messages")
    ] = None
    messages_removed: Annotated[
        int | None, Field(description="Messages removed with the chat (delete)")
    ] = None
    continuation: Annotated[
        str | None,
        Field(description="send only: new, chained (from the last response id) or replay"),
    ] = None
    answer: Annotated[str | None, Field(description="send: the answer text")] = None
    answer_json: Annotated[Any, Field(description="Always null: send takes no json_schema")] = None
    sources: Annotated[
        list[Source], Field(description="send: pages the run found or fetched, by first use")
    ] = []
    status: Annotated[str | None, Field(description="send: completed or incomplete")] = None
    incomplete_reason: Annotated[str | None, Field(description="send: why it stopped")] = None
    warnings: Annotated[list[str], Field(description="Things worth knowing about this result")] = []
    model: Annotated[str | None, Field(description="send: the model that answered")] = None
    depth: Annotated[str | None, Field(description="send: the preset used")] = None
    response_id: Annotated[str | None, Field(description="send: the API's response id")] = None
    usage: Annotated[UsageSummary | None, Field(description="send: tokens and cost")] = None
    latency_ms: Annotated[int | None, Field(description="send: upstream call wall time")] = None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def chat_info(chat: ChatSummary) -> ChatInfo:
    return ChatInfo(
        id=chat.id,
        title=chat.title,
        message_count=chat.message_count,
        created_at=_utc(chat.created_at),
        updated_at=_utc(chat.updated_at),
    )


def message_out(message: StoredMessage) -> ChatMessageOut:
    sources: list[Source] = []
    if message.sources_json:
        try:
            sources = [Source(**item) for item in json.loads(message.sources_json)]
        except (ValueError, TypeError):
            sources = []  # a hand-edited row must not break reading the chat
    return ChatMessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        created_at=_utc(message.created_at),
        response_id=message.response_id,
        model=message.model,
        preset=message.preset,
        sources=sources,
    )


def _bad(option: str, message: str) -> PerplexityError:
    return PerplexityError("invalid_request", f"{option}: {message}")


def _not_found_project(name: str) -> PerplexityError:
    return PerplexityError("not_found", f"No project named {name!r}.")


def _message_item(role: str, content: str) -> dict[str, str]:
    return {"type": "message", "role": role, "content": content}


async def _send(
    app: Any,
    *,
    project: str | None,
    message: str | None,
    title: str | None,
    chat_id: int | None,
    replay: bool,
    options: AskOptions,
) -> tuple[ChatResult, str]:
    # 1. Everything local, before any database access or request.
    check_text("message", message)
    if chat_id is not None:
        chat_id = check_row_id("chat_id", chat_id)
    clean_title = ""
    if chat_id is None:
        if replay:
            raise _bad("replay", "needs a chat_id: there is no stored history to resend.")
        if not isinstance(title, str) or not title.strip():
            raise _bad("title", "is required to start a chat (1 to 120 characters).")
        clean_title = check_text("title", title.strip(), MAX_TITLE_CHARS)
    elif title is not None:
        raise _bad("title", "cannot be given with a chat_id; chats are not renamed.")
    build_request(options, message, store=False)  # validates every option; discarded
    name = validate_project_name(project or DEFAULT_PROJECT)

    # 2. Find the chat (read-only; the project is never created here).
    project_id = anchor = None
    history: list[tuple[str, str]] = []
    if chat_id is not None:
        async with unit_of_work(app.engine, write=False) as session:
            found = await find_project(session, name)
            if found is None:
                raise _not_found_project(name)
            project_id = found.id
            await load_chat(session, project_id, chat_id)
            if replay:
                history = await chat_history(session, chat_id)
            else:
                anchor = await last_anchor(session, chat_id)
        if not replay and anchor is None:
            raise _bad(
                "chat_id",
                f"chat {chat_id} has no stored response to continue from; send with replay true.",
            )

    # 3. The request.
    warnings: list[str] = []
    if replay:
        items = [_message_item(role, content) for role, content in history]
        items.append(_message_item("user", message))
        stored = sum(len(content) for _, content in history)
        if stored > REPLAY_WARN_CHARS:
            warnings.append(
                f"A replay resends all {stored:,} stored characters on every turn; this "
                "chat's history is large, so each send costs more."
            )
        body = build_request(options, items, store=False)
        continuation = "replay"
    elif chat_id is not None:
        body = build_request(options, message, store=False, previous_response_id=anchor)
        continuation = "chained"
    else:
        body = build_request(options, message, store=False)
        continuation = "new"

    # 4. The upstream call: recorded by run_costed, no write unit open.
    try:
        costed = await run_costed(
            app,
            tool=TOOL,
            project=name,
            body=body,
            preset=options.preset,
            background=False,
            resolve_project=chat_id is None,
        )
    except PerplexityError as exc:
        raise (continuation_hint(exc) if continuation == "chained" else exc) from None
    secrets = (app.settings.api_key.get_secret_value(),)
    answer = digest(costed.run, secrets=secrets)

    # 5. Only now the chat's own write: one short unit, after the event was recorded.
    saved: ChatSummary | None = None
    complete = answer.status == "completed"  # an incomplete turn is returned, never stored
    # The anchor of the next chained send: stored only when it is a response id (and holds no
    # key); otherwise None, and the next send must replay.
    stored_id = clean_text(costed.run.id, 128, secrets)
    turn = AssistantTurn(
        response_id=stored_id if is_response_id(stored_id) else None,
        content=answer.answer,
        model=answer.model,
        preset=options.preset,
        sources_json=json.dumps([s.model_dump() for s in answer.sources]),
    )

    async def write_turn() -> ChatSummary:
        async with unit_of_work(app.engine) as session:
            if chat_id is None:
                found = await find_project(session, name)
                if found is None:
                    raise _not_found_project(name)
                return await create_chat(
                    session,
                    found.id,
                    scrub_secrets(clean_title, secrets),
                    scrub_secrets(message, secrets),
                    turn,
                )
            return await append_turn(
                session, project_id, chat_id, scrub_secrets(message, secrets), turn
            )

    try:
        if complete:
            # Shielded: the answer is billed, so a client cancel must not lose the row.
            saved = await shielded_write(write_turn())
    except PerplexityError as exc:
        if exc.category == "not_found":
            raise
        warnings.append(_not_saved(exc.category))
    except Exception as exc:  # no exc_info: a database error renders every bound value
        logger.error(
            "chat write failed after a completed upstream call: %s", failure_summary(exc, secrets)
        )
        warnings.append(_not_saved("internal_error"))

    answer.warnings.extend(warnings)  # the readable text and the structured result agree
    ask = build_result(
        answer, depth=options.preset, latency_ms=costed.latency_ms, project=costed.project
    )
    result = ChatResult(
        action="send",
        project=costed.project,
        chat_id=saved.id if saved else chat_id,
        chat=chat_info(saved) if saved else None,
        continuation=continuation,
        **ask.model_dump(exclude={"project"}),
    )
    header = f"Chat {result.chat_id}" if result.chat_id is not None else "No chat saved"
    return result, f"{header} ({continuation}).\n\n" + render_answer(ask)


def _limit(value: int | None, default: int, high: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= high:
        raise _bad("limit", f"must be a whole number from 1 to {high}.")
    return value


def _need_chat_id(chat_id: int | None, action: str) -> int:
    if chat_id is None:
        raise _bad("chat_id", f"{action} needs a chat_id.")
    return check_row_id("chat_id", chat_id)


async def _list(app: Any, *, project: str | None, limit: int | None) -> tuple[ChatResult, str]:
    """The project's chats; a project that does not exist has none (and is not created)."""
    cap = _limit(limit, DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT)
    name = validate_project_name(project or DEFAULT_PROJECT)
    chats: list[ChatSummary] = []
    total = 0
    async with unit_of_work(app.engine, write=False) as session:
        found = await find_project(session, name)
        if found is not None:
            chats, total = await list_chats(session, found.id, cap)
    result = ChatResult(
        action="list",
        project=name,
        chats=[chat_info(c) for c in chats],
        chats_total=total,
        truncated=total > len(chats),
    )
    lines = [f"{len(chats)} of {total} chat(s) in project {name!r}, newest first:"]
    lines.extend(
        f"{c.id}. {c.title} ({c.message_count} messages, "
        f"updated {_utc(c.updated_at):%Y-%m-%d %H:%M} UTC)"
        for c in chats
    )
    if total > len(chats):
        lines.append(f"(cut by limit {cap}; {total - len(chats)} more)")
    return result, "\n".join(lines)


async def _read(
    app: Any, *, project: str | None, chat_id: int | None, limit: int | None
) -> tuple[ChatResult, str]:
    chat_id = _need_chat_id(chat_id, "read")
    cap = _limit(limit, DEFAULT_READ_LIMIT, MAX_READ_LIMIT)
    name = validate_project_name(project or DEFAULT_PROJECT)
    async with unit_of_work(app.engine, write=False) as session:
        found = await find_project(session, name)
        if found is None:
            raise _not_found_project(name)
        chat = await load_chat(session, found.id, chat_id)
        info = await chat_summary(session, chat)
        messages, total = await read_messages(session, chat_id, cap)
    result = ChatResult(
        action="read",
        project=name,
        chat_id=chat_id,
        chat=chat_info(info),
        messages=[message_out(m) for m in messages],
        messages_total=total,
        truncated=total > len(messages),
    )
    lines = [f"Chat {chat_id} {info.title!r}: {len(messages)} of {total} message(s)."]
    for m in messages:
        lines.extend(["", f"[{m.role}] {m.content}"])
    return result, "\n".join(lines)


async def _delete(
    app: Any, *, project: str | None, chat_id: int | None, confirm: bool
) -> tuple[ChatResult, str]:
    chat_id = _need_chat_id(chat_id, "delete")
    name = validate_project_name(project or DEFAULT_PROJECT)
    if confirm is not True:
        raise PerplexityError(
            "confirmation_required",
            f"Deleting chat {chat_id} removes it and its messages from the local database and "
            "cannot be undone; copies the provider keeps are not touched. Call again with "
            "confirm=true.",
        )
    async with unit_of_work(app.engine) as session:
        found = await find_project(session, name)
        if found is None:
            raise _not_found_project(name)
        removed = await delete_chat(session, found.id, chat_id)
    result = ChatResult(action="delete", project=name, chat_id=chat_id, messages_removed=removed)
    return result, f"Chat {chat_id} removed with its {removed} message(s)."


def continuation_hint(exc: PerplexityError) -> PerplexityError:
    """The API rejects an unknown, malformed, unfinished or cancelled ``previous_response_id``
    with one generic 400, the same body it gives for other mistakes (design D6). Only that exact
    body on a chained send is rewritten; any other error, including a 400 that says what is
    wrong, passes through untouched. No retry: a hidden second call would double the bill."""
    if (
        exc.category == "invalid_request"
        and exc.status == 400
        and exc.api_type == "invalid_request"
        and exc.api_message == GENERIC_400
    ):
        return PerplexityError(
            "invalid_request",
            "The provider could not continue from the previous response (it answered "
            f"{GENERIC_400!r}): the stored response id may have expired or been rejected. "
            "Send again with replay true to resend the stored history.",
            status=exc.status,
            api_type=exc.api_type,
            api_code=exc.api_code,
            api_message=exc.api_message,
        )
    return exc


def _not_saved(category: str) -> str:
    return (
        f"not_saved: the answer was returned but could not be stored in the chat ({category}); "
        "the usage event was kept, and the next send continues from the last stored turn."
    )


def register(server: FastMCP) -> None:
    @server.tool(
        name=TOOL,
        output_schema=ChatResult.model_json_schema(),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True),
    )
    async def perplexity_chat(
        ctx: Context,
        action: Annotated[str, Field(description="send, list, read or delete")],
        message: Annotated[
            str | None,
            Field(description="send: the message (at most 20000 characters, not blank)"),
        ] = None,
        title: Annotated[
            str | None,
            Field(description="send, new chat only: its title, 1 to 120 characters (required)"),
        ] = None,
        chat_id: Annotated[
            int | None, Field(description="send: continue this chat; omit to start a new one")
        ] = None,
        project: Annotated[
            str | None, Field(description="Project the chat belongs to (default: default)")
        ] = None,
        replay: Annotated[
            bool,
            Field(
                description="send: resend the stored history instead of continuing from the "
                "previous response id (use it when the provider cannot continue)"
            ),
        ] = False,
        depth: Annotated[
            str | None,
            Field(description="send: fast (default), low or medium; may change on every turn"),
        ] = None,
        model: Annotated[
            str | None,
            Field(description="send: an explicit model id instead of a depth (see perplexity_ask)"),
        ] = None,
        search: Annotated[
            bool | None, Field(description="send: false answers from the model alone (needs model)")
        ] = None,
        domains: Annotated[
            list[str] | None,
            Field(description="send: at most 20 domains, all allowed or all denied with '-'"),
        ] = None,
        recency: Annotated[
            str | None, Field(description="send: hour, day, week, month or year")
        ] = None,
        after: Annotated[
            str | None, Field(description="send: only results after this date (YYYY-MM-DD)")
        ] = None,
        before: Annotated[
            str | None, Field(description="send: only results before this date (YYYY-MM-DD)")
        ] = None,
        country: Annotated[
            str | None, Field(description="send: two-letter country code to localize the search")
        ] = None,
        max_results: Annotated[
            int | None, Field(description="send: search results to retrieve, 1 to 50")
        ] = None,
        instructions: Annotated[
            str | None, Field(description="send: system-style instructions, at most 10000 chars")
        ] = None,
        max_output_tokens: Annotated[
            int | None, Field(description="send: cap on answer tokens, 1 to 64000")
        ] = None,
        limit: Annotated[
            int | None,
            Field(
                description="list: chats to return, 1 to 100 (default 20), newest first. read: "
                "the last N messages, 1 to 200 (default 50)"
            ),
        ] = None,
        confirm: Annotated[
            bool, Field(description="delete: must be true; removing a chat cannot be undone")
        ] = False,
    ) -> ToolResult:
        """Hold a multi-turn conversation grounded in web search. A send continues the chat
        from its last stored response; the messages are kept in this server's local database.
        Actions: send (starts a chat when chat_id is omitted), list, read and delete.

        Approximate cost per send by depth (observed ranges; the upper figures are estimates):
        fast $0.001 to $0.002 (the default), low $0.0005 to $0.004 (up to about $0.02
        estimated), medium $0.016 to $0.017 as a research run (up to about $0.05 estimated;
        a synchronous medium send was not measured); high and xhigh are not available here
        (use perplexity_research). Every send is recorded as spend (see perplexity_usage).
        list, read and delete make no upstream call and cost nothing; they read or change only
        the local database and never create a project.

        Chat text is stored in the local database. A send sets store to false, which only hides
        the response from retrieval at the provider; the provider's documentation says it still
        persists state, so this is not a retention control. If the provider cannot continue from
        the previous response, send again with replay true to resend the stored history."""
        if action not in ACTIONS:
            raise _bad("action", f"must be one of {', '.join(ACTIONS)}.")
        options = AskOptions(
            depth=depth,
            model=model,
            search=search,
            domains=domains,
            recency=recency,
            after=after,
            before=before,
            country=country,
            max_results=max_results,
            instructions=instructions,
            max_output_tokens=max_output_tokens,
        )
        app = ctx.lifespan_context
        if action == "list":
            result, text = await _list(app, project=project, limit=limit)
        elif action == "read":
            result, text = await _read(app, project=project, chat_id=chat_id, limit=limit)
        elif action == "delete":
            result, text = await _delete(app, project=project, chat_id=chat_id, confirm=confirm)
        else:
            result, text = await _send(
                app,
                project=project,
                message=message,
                title=title,
                chat_id=chat_id,
                replay=replay,
                options=options,
            )
        return ToolResult(content=text, structured_content=result.model_dump(mode="json"))
