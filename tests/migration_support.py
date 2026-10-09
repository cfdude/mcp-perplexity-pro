"""Helpers for the migration tests: the real revision chain, so no test hard-codes a head."""

from alembic.script import ScriptDirectory

from mcp_perplexity_pro.storage.migrate import MIGRATIONS_DIR, _config


def real_chain() -> list[str]:
    """The real revisions, base to head, read from the migrations directory."""
    script = ScriptDirectory.from_config(_config(MIGRATIONS_DIR))
    return [r.revision for r in reversed(list(script.walk_revisions()))]
