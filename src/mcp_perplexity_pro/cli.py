"""Command-line arguments, parsed before settings load so ``--help`` needs no environment."""

from __future__ import annotations

import argparse
from importlib.metadata import version

EPILOG = """\
environment variables (prefix PERPLEXITY_):
  PERPLEXITY_API_KEY            required; the Perplexity API key
  PERPLEXITY_HOST               HTTP bind host (default 127.0.0.1)
  PERPLEXITY_PORT               HTTP port (default 8102)
  PERPLEXITY_BASE_URL           API base URL (default https://api.perplexity.ai)
  PERPLEXITY_DATA_DIR           data directory (default ~/.perplexity-pro/)
  PERPLEXITY_LOG_LEVEL          DEBUG, INFO, WARNING, ERROR or CRITICAL (default INFO)
  PERPLEXITY_CONNECT_TIMEOUT    seconds (default 10)
  PERPLEXITY_READ_TIMEOUT       seconds (default 60)
  PERPLEXITY_MAX_ATTEMPTS       attempts per request (default 3)
  PERPLEXITY_MAX_RETRY_WAIT     longest retry wait in seconds (default 30)
  PERPLEXITY_CATALOG_TTL        model list cache lifetime in seconds (default 3600)
  PERPLEXITY_CATALOG_MAX_STALE  longest stale-on-failure age in seconds (default 86400)
  PERPLEXITY_DB_BUSY_TIMEOUT    database lock wait in seconds (default 5)
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-perplexity-pro",
        description="MCP server for the Perplexity API.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="how to serve MCP: over stdin/stdout, or Streamable HTTP at /mcp (default: stdio)",
    )
    parser.add_argument("--version", action="version", version=version("mcp-perplexity-pro"))
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


if __name__ == "__main__":
    parse_args()
