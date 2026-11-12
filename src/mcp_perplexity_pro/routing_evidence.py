"""The router's benchmark evidence: one versioned file, read like the matrix baseline (D1, D2).

Pure and synchronous: no network, no engine, no FastMCP. It holds

* the ``Evidence`` model (``routing_evidence.json``: task classes, benchmarks, the shortlist, the
  fallbacks and per-model scores, each score carrying its source, date and basis);
* ``load`` (the data-directory file, else the packaged one; a missing, corrupt, invalid or newer
  file never replaces it silently: one warning, then the packaged evidence);
* ``EvidenceState``, the one lazy holder an ``AppContext`` carries (no read at construction, so
  ``perplexity-pro help`` and the schema builder touch no file);
* the class mean (``class_score``) that selection reads: the arithmetic mean, in exact ``Decimal``,
  of a model's VERIFIED scores for every benchmark id the class lists.

A score with ``verified_at`` null is TO BE SOURCED: kept, never used. The server never writes the
file. A score whose ``source_url`` is on ``llm-stats.com`` is rejected: that aggregator is a lead,
never a source.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

VERSION = 1
FILENAME = "routing_evidence.json"
PACKAGED_RESOURCE = "data/routing_evidence.json"
MAX_FILE_BYTES = 1024 * 1024
STALE_DAYS = 90
BLOCKED_HOSTS = ("llm-stats.com",)

LoadState = Literal["ok", "missing", "corrupt", "invalid", "newer", "unreadable"]


def today_utc() -> date:
    return datetime.now(UTC).date()


class Score(BaseModel):
    """One sourced figure. Every field but ``harness`` and ``verified_at`` is required, and those
    two are required to be PRESENT (text or null): a figure with no provenance is how a number
    gets invented, so a missing field is an invalid file, never a silent skip."""

    model_config = ConfigDict(extra="ignore", strict=False)

    score: Decimal = Field(ge=0, le=100)
    source_url: str
    as_of: date
    basis: Literal["independent", "vendor"]
    harness: str | None
    verified_at: date | None

    @field_validator("score", mode="before")
    @classmethod
    def _a_real_number(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
            raise ValueError("score must be a number")
        return value

    @field_validator("source_url")
    @classmethod
    def _https_and_not_an_aggregator(cls, value: str) -> str:
        parts = urlsplit(value)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not host:
            raise ValueError("source_url must be an https URL")
        if any(host == h or host.endswith("." + h) for h in BLOCKED_HOSTS):
            raise ValueError("a source_url on llm-stats.com is a lead, never a source")
        return value


class Benchmark(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str


class TaskClass(BaseModel):
    model_config = ConfigDict(extra="ignore")

    benchmarks: list[str] = Field(min_length=1)


class Fallback(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    effort: str


class ModelEvidence(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scores: dict[str, Score] = Field(default_factory=dict)


class Evidence(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: int = VERSION
    as_of: date
    task_classes: dict[str, TaskClass]
    benchmarks: dict[str, Benchmark]
    shortlist: list[str]
    fallbacks: dict[str, Fallback]
    models: dict[str, ModelEvidence]

    def check(self, today: date) -> None:
        """The cross-field rules a per-field validator cannot see; raises ``ValueError`` naming
        the offender."""
        if self.version != VERSION:
            raise ValueError(f"unknown version {self.version}")
        for name, task_class in self.task_classes.items():
            for benchmark in task_class.benchmarks:
                if benchmark not in self.benchmarks:
                    raise ValueError(f"class {name} lists unknown benchmark {benchmark}")
        if "default" not in self.fallbacks:
            raise ValueError("fallbacks.default is missing")
        for model_id in (*self.shortlist, self.fallbacks["default"].model):
            if model_id not in self.models:
                raise ValueError(f"{model_id} has no entry under models")
        for model_id, entry in self.models.items():
            for benchmark, figure in entry.scores.items():
                verified = figure.verified_at
                if verified is not None and (verified < figure.as_of or verified > today):
                    raise ValueError(
                        f"{model_id} {benchmark}: verified_at {verified} is before as_of "
                        f"{figure.as_of} or in the future"
                    )

    # --- what selection reads ---------------------------------------------------------------

    def class_score(self, model_id: str, task_class: str) -> Decimal | None:
        """The model's score for a class: the mean of its VERIFIED scores for every benchmark id
        the class lists (matched by id, so another version of a benchmark does not count), else
        ``None`` (a class that is absent or lists nothing is ineligible for every model)."""
        spec = self.task_classes.get(task_class)
        entry = self.models.get(model_id)
        if spec is None or entry is None or not spec.benchmarks:
            return None
        total = Decimal(0)
        for benchmark in spec.benchmarks:
            figure = entry.scores.get(benchmark)
            if figure is None or figure.verified_at is None:
                return None
            total += figure.score
        return total / len(spec.benchmarks)

    def has_verified_score(self) -> bool:
        return any(
            figure.verified_at is not None
            for entry in self.models.values()
            for figure in entry.scores.values()
        )


# --- load -------------------------------------------------------------------------------------


def load_packaged(today: date | None = None) -> Evidence:
    """The evidence packaged with the code (read with ``importlib.resources``)."""
    text = files(__package__).joinpath(PACKAGED_RESOURCE).read_text()
    return parse(text, today or today_utc())


def parse(text: str, today: date) -> Evidence:
    """Parse and check one evidence document. Numbers keep their JSON text as ``Decimal``, so a
    margin test on ``80.3`` is exact. Raises ``ValueError`` (``ValidationError`` included)."""
    doc = json.loads(text, parse_float=Decimal)
    evidence = Evidence.model_validate(doc)
    evidence.check(today)
    return evidence


@dataclass(frozen=True)
class Loaded:
    """A read of the evidence: what to use, where it came from, what the file was and, when it
    was not used, the one warning that says why."""

    evidence: Evidence
    origin: Literal["file", "packaged"]
    state: LoadState
    warning: str | None = None


def _describe(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        return f"{where}: {first['msg']}"
    return str(exc)


def load(path: Path, today: date | None = None) -> Loaded:
    """Read ``path``, else the packaged evidence. Reading never writes, renames or creates."""
    day = today or today_utc()
    packaged = load_packaged(day)

    def fallback(state: LoadState, why: str) -> Loaded:
        return Loaded(packaged, "packaged", state, f"routing evidence {path} {why}; using packaged")

    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        return Loaded(packaged, "packaged", "missing")
    except OSError:
        return fallback("unreadable", "could not be read")
    if len(raw) > MAX_FILE_BYTES or not raw.strip():
        return fallback("corrupt", "is empty or too large")
    try:
        doc = json.loads(raw, parse_float=Decimal)
    except (ValueError, RecursionError):
        return fallback("corrupt", "is not JSON")
    version = doc.get("version") if isinstance(doc, dict) else None
    if isinstance(version, int) and not isinstance(version, bool) and version > VERSION:
        return fallback("newer", f"has version {version}")
    try:
        evidence = Evidence.model_validate(doc)
        evidence.check(day)
    except (ValueError, ValidationError) as exc:
        return fallback("invalid", f"is invalid ({_describe(exc)})")
    return Loaded(evidence, "file", "ok")


@dataclass
class EvidenceState:
    """The holder an ``AppContext`` carries: ``snapshot()`` reads on first use and keeps the
    result, logging the one warning of a rejected file exactly once. Nothing reads at
    construction and nothing is ever written."""

    data_dir: Path
    today: Callable[[], date] = today_utc
    _loaded: Loaded | None = field(default=None, repr=False)

    def snapshot(self) -> Loaded:
        if self._loaded is None:
            self._loaded = load(self.data_dir / FILENAME, self.today())
            if self._loaded.warning:
                logger.warning(self._loaded.warning)
        return self._loaded
