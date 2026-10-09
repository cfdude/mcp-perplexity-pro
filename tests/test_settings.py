"""Settings: names, defaults, validation messages and the absence of side effects."""

import os
from pathlib import Path

import pytest

from mcp_perplexity_pro.settings import Settings, SettingsError, load_settings

KEY = "test-dummy-api-key"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Start every test with no PERPLEXITY_ variables from the developer's shell."""
    for name in list(os.environ):
        if name.upper().startswith("PERPLEXITY_"):
            monkeypatch.delenv(name)


@pytest.fixture
def key_env(monkeypatch):
    monkeypatch.setenv("PERPLEXITY_API_KEY", KEY)


def test_documented_defaults(key_env):
    s = load_settings()
    assert s.host == "127.0.0.1"
    assert s.port == 8102
    assert s.base_url == "https://api.perplexity.ai"
    assert s.data_dir == Path.home() / ".perplexity-pro"
    assert s.log_level == "INFO"
    assert s.connect_timeout == 10
    assert s.read_timeout == 60
    assert s.agent_read_timeout == 120
    assert s.max_attempts == 3
    assert s.max_retry_wait == 30
    assert s.catalog_ttl == 3600
    assert s.catalog_max_stale == 86400
    assert s.db_busy_timeout == 5


def test_every_documented_name_is_overridable(monkeypatch, tmp_path):
    values = {
        "API_KEY": KEY,
        "HOST": "0.0.0.0",
        "PORT": "8199",
        "BASE_URL": "http://127.0.0.1:9",
        "DATA_DIR": str(tmp_path / "d"),
        "LOG_LEVEL": "debug",
        "CONNECT_TIMEOUT": "1.5",
        "READ_TIMEOUT": "2.5",
        "AGENT_READ_TIMEOUT": "240",
        "MAX_ATTEMPTS": "5",
        "MAX_RETRY_WAIT": "7",
        "CATALOG_TTL": "11",
        "CATALOG_MAX_STALE": "22",
        "DB_BUSY_TIMEOUT": "9",
    }
    for name, value in values.items():
        monkeypatch.setenv(f"PERPLEXITY_{name}", value)
    s = load_settings()
    assert (s.host, s.port, s.base_url) == ("0.0.0.0", 8199, "http://127.0.0.1:9")
    assert s.data_dir == tmp_path / "d"
    assert s.log_level == "DEBUG"
    assert (s.connect_timeout, s.read_timeout, s.agent_read_timeout) == (1.5, 2.5, 240)
    assert (s.max_attempts, s.max_retry_wait) == (5, 7)
    assert (s.catalog_ttl, s.catalog_max_stale, s.db_busy_timeout) == (11, 22, 9)


def test_missing_api_key_names_the_variable():
    with pytest.raises(SettingsError) as excinfo:
        load_settings()
    assert "PERPLEXITY_API_KEY" in str(excinfo.value)


def test_empty_api_key_is_rejected_without_echo(monkeypatch):
    monkeypatch.setenv("PERPLEXITY_API_KEY", "")
    with pytest.raises(SettingsError, match="PERPLEXITY_API_KEY"):
        load_settings()


def test_non_integer_port_names_variable_and_value(key_env, monkeypatch):
    monkeypatch.setenv("PERPLEXITY_PORT", "eighty")
    with pytest.raises(SettingsError) as excinfo:
        load_settings()
    message = str(excinfo.value)
    assert "PERPLEXITY_PORT" in message
    assert "eighty" in message


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PORT", "0"),
        ("PORT", "70000"),
        ("MAX_ATTEMPTS", "0"),
        ("CONNECT_TIMEOUT", "-1"),
        ("LOG_LEVEL", "LOUD"),
        ("BASE_URL", "not a url"),
    ],
)
def test_out_of_range_values_name_the_variable(key_env, monkeypatch, name, value):
    monkeypatch.setenv(f"PERPLEXITY_{name}", value)
    with pytest.raises(SettingsError, match=f"PERPLEXITY_{name}"):
        load_settings()


def test_all_problems_are_reported_together(monkeypatch):
    monkeypatch.setenv("PERPLEXITY_PORT", "x")
    with pytest.raises(SettingsError) as excinfo:
        load_settings()
    message = str(excinfo.value)
    assert "PERPLEXITY_API_KEY" in message
    assert "PERPLEXITY_PORT" in message


def test_error_message_never_contains_the_key(monkeypatch):
    secret = "pplx-" + "a" * 40
    monkeypatch.setenv("PERPLEXITY_API_KEY", secret)
    monkeypatch.setenv("PERPLEXITY_PORT", "x")
    with pytest.raises(SettingsError) as excinfo:
        load_settings()
    assert secret not in str(excinfo.value)
    assert secret not in repr(excinfo.value)


def test_key_is_a_secret_and_not_in_repr(key_env):
    s = load_settings()
    assert s.api_key.get_secret_value() == KEY
    assert KEY not in repr(s)
    assert KEY not in str(s)
    assert KEY not in s.model_dump_json()


def test_unknown_variables_are_ignored(key_env, monkeypatch):
    monkeypatch.setenv("PERPLEXITY_NOT_A_SETTING", "1")
    assert load_settings().port == 8102


def test_dotenv_file_is_not_read(key_env, monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("PERPLEXITY_PORT=1234\nPERPLEXITY_HOST=0.0.0.0\n")
    monkeypatch.chdir(tmp_path)
    s = load_settings()
    assert (s.host, s.port) == ("127.0.0.1", 8102)
    assert Settings.model_config.get("env_file") is None


def test_creating_settings_touches_no_disk(key_env, monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(cwd)
    s = load_settings()
    assert s.data_dir == home / ".perplexity-pro"
    assert not s.data_dir.exists()
    assert list(home.iterdir()) == []
    assert list(cwd.iterdir()) == []


def test_tilde_in_data_dir_is_expanded(key_env, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PERPLEXITY_DATA_DIR", "~/elsewhere")
    assert load_settings().data_dir == tmp_path / "elsewhere"


@pytest.mark.parametrize("value", ["0", "soon"])
def test_agent_read_timeout_rejects_bad_values_naming_variable_and_value(
    key_env, monkeypatch, value
):
    monkeypatch.setenv("PERPLEXITY_AGENT_READ_TIMEOUT", value)
    with pytest.raises(SettingsError) as excinfo:
        load_settings()
    message = str(excinfo.value)
    assert "PERPLEXITY_AGENT_READ_TIMEOUT" in message
    assert repr(value) in message


def test_agent_read_timeout_override_is_a_float(key_env, monkeypatch):
    monkeypatch.setenv("PERPLEXITY_AGENT_READ_TIMEOUT", "240")
    assert load_settings().agent_read_timeout == 240.0
