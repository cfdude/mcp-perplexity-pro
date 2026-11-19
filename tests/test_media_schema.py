"""Task 3.2: this change adds nothing to the schema, and no media-owned module reaches for the
router's pieces (split plan: ``acceptance/split-plan.md``, "Code rule for the build tasks")."""

import sqlite3
from pathlib import Path

import pytest

from mcp_perplexity_pro.storage.engine import database_path
from mcp_perplexity_pro.storage.migrate import MIGRATIONS_DIR, migrate

SRC = Path(__file__).resolve().parent.parent / "src" / "mcp_perplexity_pro"
# the modules this change owns (call_flow.py is the media-owned scaffolding of its task 5.3a)
MEDIA_OWNED = (
    "media.py",
    "media_read.py",
    "media_gate.py",
    "media_notes.py",
    "call_flow.py",
    "probe_media.py",
)
# spelled in pieces so this file does not hold the words it forbids elsewhere
FORBIDDEN = (
    "routing" + "_select",
    "routing" + "_evidence",
    "rou" + "ter",
    "held " + "model",
    "routed" + "_model",
    "chat_messages." + "tier",
)


def test_no_column_of_any_table_is_named_for_an_attachment(make_settings):
    settings = make_settings()
    migrate(settings)
    with sqlite3.connect(database_path(settings.data_dir)) as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert "chat_messages" in tables
        columns = [
            (table, row[1]) for table in tables for row in db.execute(f"PRAGMA table_info({table})")
        ]
    assert [c for c in columns if "attachment" in c[1].lower()] == []
    assert [t for t in tables if "attachment" in t.lower()] == []


def test_no_migration_revision_belongs_to_this_change():
    versions = sorted((Path(MIGRATIONS_DIR) / "versions").glob("[0-9]*.py"))
    assert versions, "the migrations were not found"
    for path in versions:
        text = (path.name + path.read_text()).lower()
        assert "attachment" not in text and "media" not in text, path.name


@pytest.mark.parametrize("name", MEDIA_OWNED)
def test_a_media_owned_module_names_nothing_the_router_owns(name):
    path = SRC / name
    if not path.exists():
        pytest.skip(f"{name} does not exist")
    text = path.read_text().lower()
    assert [word for word in FORBIDDEN if word in text] == []
