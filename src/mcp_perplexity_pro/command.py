"""The ``perplexity-pro`` command: one subcommand per tool, generated from the tool schemas.

The parser is built offline (no key, no network, no data directory): ``schema_source()`` builds
the real server over an unused in-memory engine and reads each tool's input schema. Running a
command calls the registered tool in-process, so there is one code path with the MCP tools (cli
spec). The argument mapping is fixed and small (design D4).
"""

from __future__ import annotations

import os

# FastMCP checks PyPI and writes a cache file under the user's home when it starts; this module
# builds a server before ``bootstrap`` runs, so the switch is set before the first import.
os.environ.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import re  # noqa: E402
import shlex  # noqa: E402
import sys  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from importlib.metadata import version  # noqa: E402
from typing import Any  # noqa: E402

from mcp_perplexity_pro import help_text  # noqa: E402

PREFIX = "perplexity_"
EXTRA_COMMANDS = ("help", "serve")


@dataclass
class ToolSpec:
    name: str  # perplexity_ask
    command: str  # ask
    schema: dict[str, Any]
    annotations: dict[str, Any] = field(default_factory=dict)

    @property
    def required(self) -> list[str]:
        return list(self.schema.get("required") or [])

    @property
    def properties(self) -> dict[str, Any]:
        return dict(self.schema.get("properties") or {})


def settings_for_help():
    """Settings for the offline server and for help: a placeholder key, the environment when it
    is valid, and the defaults (with ``warning`` set) when it is not."""
    from pydantic import ValidationError
    from pydantic_settings import SettingsConfigDict

    from mcp_perplexity_pro.settings import ENV_PREFIX, Settings

    key = os.environ.get(f"{ENV_PREFIX}API_KEY") or "unused"
    try:
        return Settings(api_key=key), None  # type: ignore[call-arg]
    except ValidationError:

        class Defaults(Settings):
            model_config = SettingsConfigDict(
                env_prefix="__PERPLEXITY_CLI_IGNORED__", env_file=None
            )

        return Defaults(api_key=key), "the environment is invalid; showing default settings"  # type: ignore[call-arg]


def schema_source() -> list[ToolSpec]:
    """Every registered tool's name, input schema and annotations, read from the real server
    built over an unused in-memory engine: no key, no network, no file."""
    import httpx2
    from sqlalchemy.ext.asyncio import create_async_engine

    from mcp_perplexity_pro.server import build_server

    settings, _warning = settings_for_help()

    async def read() -> list[ToolSpec]:
        engine = create_async_engine("sqlite+aiosqlite://")
        http = httpx2.AsyncClient()
        try:
            server = build_server(settings, http, engine)
            tools = await server.list_tools()
            return [
                ToolSpec(
                    name=t.name,
                    command=t.name.removeprefix(PREFIX),
                    schema=t.parameters,
                    annotations=(
                        t.annotations.model_dump(by_alias=True, exclude_none=True)
                        if t.annotations
                        else {}
                    ),
                )
                for t in sorted(tools, key=lambda t: t.name)
            ]
        finally:
            await http.aclose()
            await engine.dispose()

    return asyncio.run(read())


def cli_example(tool: ToolSpec, example: dict[str, Any]) -> str:
    """The example arguments of a tool written as a ``perplexity-pro`` command line (the inverse
    of ``collect_arguments``: a test parses it back to the same arguments)."""
    if tool.name == "perplexity_help":
        return "perplexity-pro help"
    required = tool.required
    parts = ["perplexity-pro", tool.command]
    given = dict(example)
    for name in ("action", "query"):
        if name in required and name in given:
            value = given.pop(name)
            parts.extend(
                shlex.quote(str(v)) for v in (value if isinstance(value, list) else [value])
            )
    for name, value in given.items():
        flag = flag_name(name)
        kind = _kind(tool.properties[name])
        if kind == "boolean":
            parts.append(flag if value else "--no-" + flag[2:])
        elif kind in ("list", "string_or_list") and isinstance(value, list):
            for item in value:
                parts.extend([flag, shlex.quote(str(item))])
        elif kind in ("json", "text_or_json") and not isinstance(value, str):
            parts.extend([flag, shlex.quote(json.dumps(value))])
        else:
            parts.extend([flag, shlex.quote(str(value))])
    return " ".join(parts)


# --- schema to argparse ---------------------------------------------------------------------


def _variants(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The non-null alternatives of a property schema."""
    options = spec.get("anyOf") or spec.get("oneOf")
    if not options:
        return [spec]
    return [o for o in options if o.get("type") != "null"]


def _kind(spec: dict[str, Any]) -> str:
    """One of: string, integer, number, boolean, list, json, text_or_json, string_or_list."""
    variants = _variants(spec)
    types = {v.get("type") for v in variants}
    if len(variants) == 1:
        v = variants[0]
        t = v.get("type")
        if t == "array":
            return "list" if (v.get("items") or {}).get("type") == "string" else "json"
        if t in ("string", "integer", "number", "boolean"):
            return str(t)
        if t == "object":
            return "json"
        return "text_or_json"  # no declared type
    if types == {"string", "array"}:
        return "string_or_list"
    return "text_or_json"


def _choices(spec: dict[str, Any]) -> list[str] | None:
    variants = _variants(spec)
    if len(variants) == 1 and "enum" in variants[0]:
        return [str(v) for v in variants[0]["enum"]]
    return None


def flag_name(parameter: str) -> str:
    return "--" + parameter.replace("_", "-")


def build_parser(tools: list[ToolSpec]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="perplexity-pro",
        description="Perplexity web-grounded answers, search, decisions and embeddings, "
        "from the command line. Every command calls the same tool the MCP server offers.",
        allow_abbrev=False,
    )
    parser.add_argument("--version", action="version", version=version("mcp-perplexity-pro"))
    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)
    for tool in tools:
        if tool.name == "perplexity_help":
            continue  # written by hand below
        _add_tool_parser(sub, tool)
    help_parser = sub.add_parser(
        "help", help="show help: the index, a tool or a topic", allow_abbrev=False
    )
    help_parser.add_argument(
        "name",
        nargs="*",
        help="a tool (ask, perplexity_ask) or a topic; 'projects' is both, so the tool wins: "
        "write 'topic projects' for the topic (or 'tool ask' to be explicit)",
    )
    serve = sub.add_parser("serve", help="run the MCP server", allow_abbrev=False)
    serve.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    return parser


def _add_tool_parser(sub: Any, tool: ToolSpec) -> None:
    entry = help_text.TOOLS.get(tool.name)
    summary = entry["summary"] if entry else tool.name
    epilog = None
    if entry:
        epilog = f"cost: {entry['cost']}\n\nexample:\n  {cli_example(tool, entry['example'])}"
    p = sub.add_parser(
        tool.command,
        help=summary,
        description=summary,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    p.set_defaults(tool=tool)
    required = tool.required
    positional: list[str] = []
    if "action" in required:
        p.add_argument(
            "action",
            nargs="?",
            choices=_choices(tool.properties["action"]),
            help=_description(tool, "action"),
        )
        positional.append("action")
    if "query" in required:
        many = _kind(tool.properties["query"]) == "string_or_list"
        p.add_argument(
            "query",
            nargs="*" if many else "?",
            help=_description(tool, "query"),
        )
        positional.append("query")
    p.set_defaults(positional=positional)
    for name, spec in tool.properties.items():
        if name in positional:
            continue
        _add_flag(p, name, spec)
    p.add_argument(
        "--args-json",
        dest="args_json",
        metavar="JSON",
        help="merge a JSON object of arguments (a JSON string, @path or - for stdin); "
        "explicit flags win",
    )
    p.add_argument(
        "--json", dest="as_json", action="store_true", help="print the structured result"
    )


def _description(tool: ToolSpec, name: str) -> str:
    return str(tool.properties.get(name, {}).get("description", ""))


def _add_flag(p: argparse.ArgumentParser, name: str, spec: dict[str, Any]) -> None:
    kind = _kind(spec)
    help_text = str(spec.get("description", ""))
    default = _default_of(spec)
    if default is not None:
        help_text = f"{help_text} (default: {default})"
    flag = flag_name(name)
    common: dict[str, Any] = {"dest": name, "default": None, "help": help_text}
    if kind == "boolean":
        p.add_argument(flag, action=argparse.BooleanOptionalAction, **common)
    elif kind in ("integer", "number"):
        p.add_argument(flag, type=int if kind == "integer" else float, **common)
    elif kind == "list":
        p.add_argument(flag, action="append", **common)
    elif kind == "string_or_list":
        p.add_argument(flag, action="append", **common)
    else:  # string, json, text_or_json: a raw string, interpreted after parsing
        choices = _choices(spec)
        if choices:
            p.add_argument(flag, choices=choices, **common)
        else:
            p.add_argument(flag, **common)


def _default_of(spec: dict[str, Any]) -> Any:
    for variant in [spec, *_variants(spec)]:
        if "default" in variant and variant["default"] is not None:
            return variant["default"]
    return None


# --- arguments ------------------------------------------------------------------------------


class UsageError(Exception):
    """A value the CLI refuses locally (exit 2, naming the flag)."""


def _load(raw: str, flag: str) -> Any:
    """A JSON value from a string, ``@path`` or ``-`` (standard input)."""
    text = raw
    if raw == "-":
        text = sys.stdin.read()
    elif raw.startswith("@"):
        try:
            with open(raw[1:], encoding="utf-8") as handle:
                text = handle.read()
        except OSError as exc:
            raise UsageError(f"{flag}: cannot read {raw[1:]!r}: {exc.strerror}") from None
    try:
        return json.loads(text)
    except ValueError:
        raise UsageError(f"{flag}: not valid JSON") from None


def _structured(raw: str, flag: str, kind: str) -> Any:
    if kind == "text_or_json":
        if raw == "-" or raw.startswith("@"):
            try:
                return _load(raw, flag)
            except UsageError:
                return raw  # text that is not JSON is kept as text
        try:
            value = json.loads(raw)
        except ValueError:
            return raw
        return value if isinstance(value, dict | list) else raw
    return _load(raw, flag)


def collect_arguments(tool: ToolSpec, ns: argparse.Namespace) -> dict[str, Any]:
    """The tool arguments from the parsed namespace: ``--args-json`` first, explicit flags and
    positionals on top, omitted parameters absent. Raises ``UsageError`` for a still-missing
    required parameter or a bad JSON value."""
    arguments: dict[str, Any] = {}
    if ns.args_json is not None:
        merged = _load(ns.args_json, "--args-json")
        if not isinstance(merged, dict):
            raise UsageError("--args-json: must be a JSON object")
        arguments.update(merged)
    for name, spec in tool.properties.items():
        value = getattr(ns, name, None)
        if name in ns.positional:
            if name == "action":
                value = value or None
            elif isinstance(value, list):
                value = None if not value else (value[0] if len(value) == 1 else value)
            elif value == "":
                value = None
        if value is None:
            continue
        kind = _kind(spec)
        if kind in ("json", "text_or_json") and isinstance(value, str):
            value = _structured(value, flag_name(name), kind)
        elif kind == "string_or_list" and isinstance(value, list):
            value = value[0] if len(value) == 1 else value
        arguments[name] = value
    missing = [n for n in tool.required if n not in arguments]
    if missing:
        raise UsageError(f"missing required argument(s): {', '.join(missing)}")
    return arguments


def parse_command(
    argv: list[str], tools: list[ToolSpec]
) -> tuple[argparse.Namespace, dict[str, Any] | None]:
    """Parse ``argv``; for a tool command also return its arguments. Exits 2 (argparse) on any
    usage error, naming the flag."""
    parser = build_parser(tools)
    ns = parser.parse_args(argv)
    if getattr(ns, "tool", None) is None:
        return ns, None
    try:
        return ns, collect_arguments(ns.tool, ns)
    except UsageError as exc:
        parser.error(str(exc))
        raise  # unreachable: parser.error exits


def run_help(words: list[str], tools: list[ToolSpec]) -> int:
    """``perplexity-pro help [<tool>|<topic>]``: the shared help text in command-line style. Needs
    no key, no network and no data directory."""
    settings, warning = settings_for_help()
    if warning:
        print(f"perplexity-pro: {warning}", file=sys.stderr)
    by_name = {t.command: t for t in tools}
    kind = None
    name = words[0] if words else None
    if len(words) == 2 and words[0] in ("tool", "topic"):
        kind, name = words
    elif len(words) > 1:
        print(
            "perplexity-pro: help takes a name, or 'tool <name>' or 'topic <name>'", file=sys.stderr
        )
        return 2
    if name is None:
        text = help_text.render_index(
            settings, [t.name for t in tools], version("mcp-perplexity-pro"), "cli"
        )
    elif (
        kind != "topic"
        and name.removeprefix(PREFIX) in by_name
        and name.removeprefix(PREFIX) != "help"
    ):
        tool = by_name[name.removeprefix(PREFIX)]
        entry = help_text.TOOLS.get(tool.name)
        text = help_text.render_tool(
            tool.name,
            settings,
            help_text.describe_params(tool.schema),
            tool.annotations,
            example=cli_example(tool, entry["example"]) if entry else None,
        )
    elif kind != "tool" and name in help_text.TOPICS:
        text = help_text.render_topic(name, settings)
    elif kind != "topic" and name.removeprefix(PREFIX) == "help":
        tool = by_name["help"]
        text = help_text.render_tool(
            tool.name,
            settings,
            help_text.describe_params(tool.schema),
            tool.annotations,
            example="perplexity-pro help",
        )
    else:
        valid = ", ".join(sorted(by_name) + list(help_text.TOPICS))
        print(f"perplexity-pro: no help for {name!r}; try one of: {valid}", file=sys.stderr)
        return 1
    print(text, end="")
    return 0


# --- running a command ----------------------------------------------------------------------

MCP_HINT = re.compile(
    r' Call perplexity_help with action "tool" and name "[a-z_]+" for its arguments and examples\.$'
)


def cli_error_text(tool: ToolSpec, category: str, message: str) -> str:
    """``[category] message`` with the MCP help sentence replaced by the command-line one."""
    cleaned = MCP_HINT.sub("", message)
    if cleaned != message:
        cleaned += f" Run perplexity-pro help {tool.command} for its arguments and examples."
    return f"[{category}] {cleaned}"


async def run_tool(
    tool: ToolSpec, arguments: dict[str, Any], as_json: bool, http: Any = None
) -> int:
    """Call ``tool`` in-process and print its result. Returns the exit status."""
    from fastmcp import Client

    from mcp_perplexity_pro.__main__ import bootstrap, close_resources

    # A command line is quiet unless asked: warnings and errors only (the operator can set
    # PERPLEXITY_LOG_LEVEL), and FastMCP's own "Error calling tool" line is not wanted because
    # the failure is printed once below, in the CLI's own form.
    quiet = "PERPLEXITY_LOG_LEVEL" not in os.environ
    if quiet:
        os.environ["PERPLEXITY_LOG_LEVEL"] = "WARNING"
    try:
        server, _settings = bootstrap(http=http, serving=False)  # exits 1 on a setup failure
    finally:
        if quiet:
            del os.environ["PERPLEXITY_LOG_LEVEL"]
    fastmcp_log = logging.getLogger("fastmcp")
    saved_level = fastmcp_log.level
    fastmcp_log.setLevel(logging.CRITICAL)
    try:
        async with Client(server) as client:
            result = await client.call_tool(tool.name, arguments, raise_on_error=False)
    finally:
        fastmcp_log.setLevel(saved_level)
        await close_resources(server)
    structured = result.structured_content or {}
    if result.is_error:
        category = str(structured.get("category", "internal_error"))
        message = str(structured.get("message", ""))
        print(cli_error_text(tool, category, message), file=sys.stderr)
        return 1
    if as_json:
        indent = 2 if sys.stdout.isatty() else None
        print(json.dumps(structured, indent=indent, ensure_ascii=False))
    else:
        print(result.content[0].text if result.content else "")
    return 0


def main(argv: list[str] | None = None, *, http: Any = None) -> int:
    """The ``perplexity-pro`` command; returns the exit status."""
    argv = list(sys.argv[1:] if argv is None else argv)
    tools = schema_source()
    ns, arguments = parse_command(argv, tools)
    if ns.command == "serve":
        return serve(ns.transport)
    try:
        if arguments is not None:
            return asyncio.run(run_tool(ns.tool, arguments, ns.as_json, http))
        if ns.command == "help":
            return run_help(ns.name, tools)
        sys.stderr.write(f"perplexity-pro {ns.command}: not available yet\n")
        return 2
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        # the reader went away (``| head``): leave quietly and keep Python from complaining
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0


def serve(transport: str) -> int:
    """``perplexity-pro serve``: the MCP server, exactly as ``mcp-perplexity-pro`` runs it."""
    from mcp_perplexity_pro.__main__ import bootstrap, run

    server, settings = bootstrap()
    run(server, settings, transport=transport)
    return 0


def cli() -> None:
    sys.exit(main())


if __name__ == "__main__":
    cli()
