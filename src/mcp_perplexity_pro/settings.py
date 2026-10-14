"""Configuration read from ``PERPLEXITY_*`` environment variables.

Creating settings is side-effect free: nothing is created or read on disk (no ``.env`` file,
no data directory). Directory creation belongs to the storage layer, after settings validate.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "PERPLEXITY_"
API_KEY_VAR = f"{ENV_PREFIX}API_KEY"

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


ROUTING_MODES = ("standard", "custom", "dynamic")
TIER_NAMES = ("light", "standard", "complex")
DEFAULT_MODEL = "perplexity/sonar"
# A model id is written into the instructions text the calling agent reads, so only the plain
# characters real ids use (no whitespace, control, invisible or Markdown characters); 200
# characters is this server's own sanity cap.
_MODEL_ID = re.compile(r"[A-Za-z0-9._:/@+-]{1,200}")


def _default_data_dir() -> Path:
    return Path.home() / ".perplexity-pro"


class Settings(BaseSettings):
    """Every setting the server reads; each maps to ``PERPLEXITY_<NAME>``."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=None,
        extra="ignore",
    )

    api_key: Annotated[SecretStr, Field(min_length=1)]
    host: Annotated[str, Field(min_length=1)] = "127.0.0.1"
    port: Annotated[int, Field(ge=1, le=65535)] = 8102
    base_url: str = "https://api.perplexity.ai"
    data_dir: Path = Field(default_factory=_default_data_dir)
    log_level: LogLevel = "INFO"
    connect_timeout: Annotated[float, Field(gt=0)] = 10
    read_timeout: Annotated[float, Field(gt=0)] = 60
    agent_read_timeout: Annotated[float, Field(gt=0)] = 120
    max_attempts: Annotated[int, Field(ge=1)] = 3
    max_retry_wait: Annotated[float, Field(ge=0)] = 30
    catalog_ttl: Annotated[float, Field(ge=0)] = 3600
    catalog_max_stale: Annotated[float, Field(ge=0)] = 86400
    db_busy_timeout: Annotated[float, Field(ge=0)] = 5
    routing: str = "standard"
    model: str = DEFAULT_MODEL
    tier_light: str | None = None
    tier_standard: str | None = None
    tier_complex: str | None = None

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("routing", mode="before")
    @classmethod
    def _lower_routing(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _check_routing(self) -> Settings:
        problems = self._routing_problems()
        if problems:
            raise ValueError("\n".join(problems))
        return self

    def _routing_problems(self) -> list[str]:
        """One line per problem, each naming its variable (never an API key)."""
        if self.routing == "dynamic":
            return [
                f"{ENV_PREFIX}ROUTING=dynamic is not available in this version "
                "(the dynamic classifier has not shipped); use standard or custom"
            ]
        if self.routing not in ROUTING_MODES:
            return [
                f"{ENV_PREFIX}ROUTING: got {self.routing!r}; accepted values are standard "
                "and custom (dynamic is reserved and not available yet)"
            ]
        wanted = (
            {"MODEL": self.model}
            if self.routing == "standard"
            else {f"TIER_{t.upper()}": getattr(self, f"tier_{t}") for t in TIER_NAMES}
        )
        problems = []
        for name, value in wanted.items():
            if value is None:
                problems.append(f"{ENV_PREFIX}{name} is required when routing is custom")
            elif not _MODEL_ID.fullmatch(value):
                problems.append(
                    f"{ENV_PREFIX}{name}: a model id is 1 to 200 characters from letters, "
                    "digits and . _ : / @ + - only"
                )
        return problems

    def ignored_routing_vars(self) -> list[str]:
        """Routing variables that are set but unused by the active mode (the caller warns)."""
        unused = ["model"] if self.routing == "custom" else [f"tier_{t}" for t in TIER_NAMES]
        return [f"{ENV_PREFIX}{n.upper()}" for n in unused if n in self.model_fields_set]

    @field_validator("data_dir", mode="after")
    @classmethod
    def _expand_user(cls, value: Path) -> Path:
        return value.expanduser()

    @field_validator("base_url", mode="after")
    @classmethod
    def _check_base_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("must be an http or https URL such as https://api.perplexity.ai")
        return value.rstrip("/")


class SettingsError(Exception):
    """Invalid or missing configuration; the message names each offending variable."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Invalid configuration:\n" + "\n".join(f"  {p}" for p in problems))


def _describe(error: dict) -> list[str]:
    if not error["loc"]:  # a cross-field check: its message already names each variable
        return [line for line in error["msg"].removeprefix("Value error, ").split("\n") if line]
    return [_describe_field(error)]


def _describe_field(error: dict) -> str:
    field = str(error["loc"][0]) if error["loc"] else "?"
    var = f"{ENV_PREFIX}{field.upper()}"
    if error["type"] == "missing":
        return f"{var} is required but not set"
    if var == API_KEY_VAR:
        return f"{var} is invalid ({error['msg']}); the value is not shown"
    return f"{var}: {error['msg']} (got {error.get('input')!r})"


def load_settings() -> Settings:
    """Read and validate settings from the environment.

    Raises ``SettingsError`` naming every offending variable. The API key value is never
    included in the message.
    """
    try:
        return Settings()  # type: ignore[call-arg]  # api_key comes from the environment
    except ValidationError as exc:
        raise SettingsError([p for e in exc.errors() for p in _describe(e)]) from None
