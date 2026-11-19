"""media-inputs task 2.1: the `inputs` facts of the model matrix and the pure interface
`accepts`, `models_accepting`, `preset_accepts`, `model_not_served`, `is_named_refusal`."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mcp_perplexity_pro import matrix
from mcp_perplexity_pro.catalog import CatalogModel, Pricing

NOW = datetime(2026, 11, 12, 9, 0, 0, tzinfo=UTC)
SRC = Path(matrix.__file__).parent

# the 54 models of the 2026-10-30 sweep (a literal list: the sweep file moves with the archive)
SWEPT = [
    "anthropic/claude-fable-5",
    "anthropic/claude-fable-5-1",
    "anthropic/claude-haiku-4-5",
    "anthropic/claude-haiku-5-5",
    "anthropic/claude-opus-4-5",
    "anthropic/claude-opus-4-6",
    "anthropic/claude-opus-4-7",
    "anthropic/claude-opus-4-8",
    "anthropic/claude-opus-5",
    "anthropic/claude-opus-5-5",
    "anthropic/claude-sonnet-4-5",
    "anthropic/claude-sonnet-4-6",
    "anthropic/claude-sonnet-5",
    "anthropic/claude-sonnet-5-5",
    "google/gemini-3-flash-preview",
    "google/gemini-3.1-flash-lite",
    "google/gemini-3.1-pro-preview",
    "google/gemini-3.5-flash",
    "google/gemini-3.5-flash-lite",
    "google/gemini-3.6-flash",
    "google/gemini-3.7-flash",
    "google/gemini-3.8-flash",
    "google/gemini-4-argon",
    "openai/gpt-5",
    "openai/gpt-5-mini",
    "openai/gpt-5-nano",
    "openai/gpt-5.1",
    "openai/gpt-5.2",
    "openai/gpt-5.3-codex",
    "openai/gpt-5.4",
    "openai/gpt-5.4-mini",
    "openai/gpt-5.4-nano",
    "openai/gpt-5.5",
    "openai/gpt-5.6-luna",
    "openai/gpt-5.6-sol",
    "openai/gpt-5.6-terra",
    "openai/gpt-6-astra",
    "openai/gpt-6-luna",
    "openai/gpt-6-sol",
    "openai/gpt-6.1-sol",
    "perplexity/deepseek-v4-pro-0813",
    "perplexity/glm-5.3",
    "perplexity/glm-5.3-flash",
    "perplexity/kimi-k3",
    "perplexity/nemotron-3-ultra-550b-a55b",
    "perplexity/nemotron-3.5-super-120b-a12b",
    "perplexity/sonar",
    "xai/grok-4.20-multi-agent",
    "xai/grok-4.20-non-reasoning",
    "xai/grok-4.20-reasoning",
    "xai/grok-4.3",
    "xai/grok-4.5",
    "xai/grok-4.6",
    "xai/grok-4.7",
]


def baseline():
    return matrix.load_baseline()


def entry(**inputs):
    return matrix.ModelEntry(
        provider="x",
        first_seen="2026-10-01T00:00:00Z",
        last_seen="2026-10-01T00:00:00Z",
        inputs=matrix.Inputs(**inputs),
    )


def mx(**models):
    return matrix.Matrix(fetched_at="2026-10-01T00:00:00Z", models=models)


def live(*ids):
    return [CatalogModel(id=i, provider=i.split("/")[0], pricing=Pricing()) for i in ids]


# --- the baseline --------------------------------------------------------------------------


def test_the_baseline_holds_the_54_swept_models_and_validates():
    base = baseline()
    assert set(SWEPT) <= set(base.models) and len(SWEPT) == 54
    assert base.version == 1


def counts(kind):
    base = baseline()
    swept = [base.models[i].inputs for i in SWEPT]
    return (
        sum(kind in i.accepted for i in swept),
        sum(kind in i.refused for i in swept),
        sum(kind not in i.accepted and kind not in i.refused for i in swept),
    )


def test_the_sweep_counts_over_the_swept_ids():
    assert counts("image") == (48, 0, 6)
    assert counts("document") == (45, 3, 6)


def test_named_models_in_the_baseline():
    m = baseline().models
    grok47 = m["xai/grok-4.7"].inputs
    assert grok47.accepted == ["image", "document"] and not grok47.refused
    assert set(grok47.probed_at.values()) == {"2026-11-11T00:00:00Z"}  # the dated override
    grok43 = m["xai/grok-4.3"].inputs
    assert grok43.refused == {"document": 400} and "image" not in grok43.accepted
    assert "image" not in m["perplexity/deepseek-v4-pro-0813"].inputs.accepted
    assert "image" not in m["perplexity/deepseek-v4-pro-0813"].inputs.refused
    assert m["openai/gpt-5-nano"].inputs.accepted == ["image", "document"]
    nemotron = m["perplexity/nemotron-3-ultra-550b-a55b"].inputs
    assert not nemotron.accepted and not nemotron.refused and nemotron.source == "unprobed"


def test_every_answered_kind_carries_the_sweep_date_and_source():
    for model_id in SWEPT:
        inputs = baseline().models[model_id].inputs
        answered = set(inputs.accepted) | set(inputs.refused)
        assert set(inputs.probed_at) == answered
        assert (inputs.source == "baseline") is bool(answered)
        for kind, at in inputs.probed_at.items():
            expected = "2026-11-11" if model_id == "xai/grok-4.7" else "2026-10-30"
            assert at.startswith(expected), (model_id, kind)
        assert not inputs.attempts and not inputs.retry_after  # a baseline answer is no attempt


def test_a_model_added_later_has_nothing_answered():
    entry_ = matrix.ModelEntry(first_seen="a", last_seen="b")
    assert entry_.inputs == matrix.Inputs() and entry_.inputs.source == "unprobed"


# --- the predicates ------------------------------------------------------------------------


def test_one_predicate_says_attempted():
    assert not matrix.attempted(matrix.Inputs(), "image")
    assert matrix.attempted(matrix.Inputs(accepted=["image"]), "image")
    assert matrix.attempted(matrix.Inputs(refused={"image": 400}), "image")
    assert matrix.attempted(matrix.Inputs(retry_after={"image": "2026-11-19T00:00:00Z"}), "image")
    assert matrix.attempted(matrix.Inputs(attempts={"image": 1}), "image")
    assert not matrix.attempted(matrix.Inputs(attempts={"image": 0}), "image")
    # per kind: the other kind's answer does not make this one attempted
    assert not matrix.attempted(matrix.Inputs(accepted=["image"]), "document")


def test_a_kind_is_known_by_its_lists_never_its_source():
    labelled_baseline = entry(accepted=["image"], source="baseline")
    labelled_probe_nothing = entry(source="probe")
    m = mx(**{"v/a": labelled_baseline, "v/b": labelled_probe_nothing})
    assert matrix.accepts("v/a", {"image"}, m) == "yes"
    assert matrix.accepts("v/b", {"image"}, m) == "unknown"
    # flipping the label changes nothing
    m2 = mx(**{"v/a": entry(accepted=["image"], source="probe")})
    assert matrix.accepts("v/a", {"image"}, m2) == "yes"


def _function_source(name):
    import inspect

    return inspect.getsource(getattr(matrix, name))


def test_no_function_reads_source_to_decide():
    for name in ("accepts", "models_accepting", "preset_accepts", "attempted", "_fill_inputs"):
        body = _function_source(name)
        # a label may be WRITTEN by the merge; nothing may compare or branch on it
        assert not re.search(r"\.source\s*(==|!=|\bin\b|\bis\b)|\bif\b[^\n]*\.source", body), name


def test_named_refusal_and_not_served_predicates():
    named = "the selected model route does not support this document type or source"
    assert matrix.NAMED_REFUSALS == (named,)
    assert matrix.is_named_refusal(400, named)
    assert not matrix.is_named_refusal(400, "invalid request")
    assert not matrix.is_named_refusal(429, "upstream model is overloaded")
    assert not matrix.is_named_refusal(200, named)
    gone = 'validation failed: model "perplexity/nemotron-3-ultra-550b-a55b" is not supported'
    assert matrix.model_not_served(400, gone, "perplexity/nemotron-3-ultra-550b-a55b")
    assert matrix.model_not_served(400, gone)
    assert not matrix.model_not_served(400, "invalid request")
    assert not matrix.model_not_served(404, "response not found", "vendor/m")
    assert matrix.model_not_served(404, 'model "vendor/m" is gone', "vendor/m")
    assert matrix.model_not_served(410, "vendor/m was retired", "vendor/m")
    assert not matrix.model_not_served(404, "vendor/m was retired")  # no model asked about
    assert not matrix.model_not_served(500, gone)
    assert not matrix.model_not_served(400, "validation failed: effort must be one of: low")


def test_the_captured_effort_refusal_is_not_a_gone_model():
    body = json.loads(
        (Path(__file__).parent / "fixtures" / "agent_effort_refused_400.json").read_text()
    )
    msg = body["error"]["message"]
    assert not matrix.model_not_served(400, msg, "openai/gpt-5-nano")
    served = json.loads(
        (Path(__file__).parent / "fixtures" / "agent_model_not_served_400.json").read_text()
    )["error"]["message"]
    assert matrix.model_not_served(400, served, "openai/gpt-99-luna")
    assert not matrix.is_named_refusal(400, served)


# --- accepts and models_accepting ----------------------------------------------------------


def test_image_capable_set():
    got = matrix.models_accepting({"image"})
    assert {"openai/gpt-6-luna", "perplexity/sonar"} <= got
    assert "perplexity/deepseek-v4-pro-0813" not in got


def test_both_kinds_is_a_subset_of_the_image_set():
    both = matrix.models_accepting({"image", "document"})
    base = baseline()
    assert both and both <= matrix.models_accepting({"image"})
    for model_id in both:
        assert {"image", "document"} <= set(base.models[model_id].inputs.accepted)


def test_a_model_the_matrix_lacks_is_unknown_and_in_no_set():
    assert matrix.accepts("vendor/unlisted", {"image"}) == "unknown"
    assert "vendor/unlisted" not in matrix.models_accepting({"image"})
    assert matrix.accepts("vendor/unlisted", set()) == "yes"


def test_any_refused_kind_is_no_even_with_another_unknown():
    m = mx(**{"v/a": entry(refused={"document": 400})})
    assert matrix.accepts("v/a", {"image", "document"}, m) == "no"
    assert matrix.accepts("v/a", {"image"}, m) == "unknown"
    assert matrix.accepts("xai/grok-4.3", {"document"}) == "no"


def test_removed_models_are_in_no_set():
    e = entry(accepted=["image"])
    e.status = "removed"
    assert "v/a" not in matrix.models_accepting({"image"}, mx(**{"v/a": e}))
    assert matrix.models_accepting(set(), mx(**{"v/a": e})) == set()


def test_empty_kinds_give_yes_and_every_available_model():
    base = baseline()
    available = {i for i, e in base.models.items() if e.status == "available"}
    assert matrix.models_accepting(set()) == available
    assert matrix.accepts("openai/gpt-6-luna", []) == "yes"


def test_a_bad_kind_raises_value_error():
    for call in (
        lambda: matrix.models_accepting({"audio"}),
        lambda: matrix.accepts("a/b", {"image", "video"}),
        lambda: matrix.preset_accepts("fast", {"audio"}),
    ):
        with pytest.raises(ValueError):
            call()


def test_no_file_is_created_and_the_baseline_is_not_modified(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = baseline().model_dump_json()
    matrix.accepts("openai/gpt-6-luna", {"image"})
    matrix.models_accepting({"image", "document"})
    assert list(tmp_path.iterdir()) == []
    assert matrix.cached_baseline().model_dump_json() == before


def test_a_file_from_before_this_change_falls_back_to_the_baseline():
    base = baseline()
    old = base.model_copy(deep=True)
    for e in old.models.values():
        e.inputs = matrix.Inputs()  # what an entry written before this change reads as
    assert matrix.models_accepting({"image"}, old) == matrix.models_accepting({"image"})
    assert matrix.accepts("xai/grok-4.3", {"document"}, old) == "no"


def test_an_attempted_unanswered_kind_stays_unknown_despite_the_baseline():
    old = baseline().model_copy(deep=True)
    e = old.models["openai/gpt-6-luna"]
    e.inputs = matrix.Inputs(
        retry_after={"document": "2026-11-19T00:00:00Z"}, unanswered_rounds={"document": 0}
    )
    assert matrix.accepts("openai/gpt-6-luna", {"document"}, old) == "unknown"
    assert matrix.accepts("openai/gpt-6-luna", {"image"}, old) == "yes"  # not attempted: baseline


def test_a_loaded_old_file_reads_as_nothing_known_and_is_not_rewritten(tmp_path):
    path = tmp_path / matrix.FILENAME
    doc = json.loads(baseline().model_dump_json())
    for e in doc["models"].values():
        e.pop("inputs")
    text = json.dumps(doc)
    path.write_text(text)
    loaded = matrix.load(path)
    assert loaded.state == "ok" and loaded.origin == "file"
    assert all(e.inputs == matrix.Inputs() for e in loaded.matrix.models.values())
    assert path.read_text() == text  # the load wrote nothing
    assert loaded.matrix.version == 1


def test_a_written_matrix_keeps_version_1(tmp_path):
    path = tmp_path / matrix.FILENAME
    matrix.write(path, baseline())
    assert json.loads(path.read_text())["version"] == 1
    again = matrix.load(path)
    assert again.matrix.models["xai/grok-4.7"].inputs.accepted == ["image", "document"]


# --- presets -------------------------------------------------------------------------------


def test_presets_are_answered_from_verified_facts_only():
    yes = [
        ("fast", "image"),
        ("low", "image"),
        ("medium", "image"),
        ("fast", "document"),
        ("medium", "document"),
    ]
    for preset, kind in yes:
        assert matrix.preset_accepts(preset, {kind}) == "yes", (preset, kind)
    assert matrix.preset_accepts("low", {"document"}) == "unknown"
    assert matrix.preset_accepts("high", {"image"}) == "unknown"
    assert matrix.preset_accepts("xhigh", {"document"}) == "unknown"
    assert matrix.preset_accepts("fast", {"image", "document"}) == "yes"
    assert matrix.preset_accepts("low", {"image", "document"}) == "unknown"
    assert matrix.preset_accepts("nonsense", {"image"}) == "unknown"
    assert matrix.preset_accepts("high", set()) == "yes"


# --- the merge -----------------------------------------------------------------------------


def stored(**models):
    return mx(**models)


def test_a_new_model_the_baseline_knows_takes_its_efforts_and_inputs():
    base = baseline()
    current = stored(**{"x/keep": entry()})
    current.models["x/keep"].status = "available"
    # keep half of the stored ids live so the truncation guard stays quiet
    merged = matrix.merge(current, live("x/keep", "xai/grok-4.3"), base, NOW)
    got = merged.matrix.models["xai/grok-4.3"]
    assert got.inputs.refused == {"document": 400} and got.inputs.source == "baseline"
    assert got.efforts.source == "baseline"
    assert got.inputs.attempts == {}


def test_a_new_model_the_baseline_lacks_has_nothing_known():
    merged = matrix.merge(stored(**{"x/keep": entry()}), live("x/keep", "v/new"), baseline(), NOW)
    assert merged.matrix.models["v/new"].inputs == matrix.Inputs()
    assert merged.matrix.models["v/new"].efforts.source == "unprobed"


def test_an_upgraded_entry_takes_the_baselines_answers_without_an_attempt():
    current = stored(**{"openai/gpt-6-luna": entry()})
    merged = matrix.merge(current, live("openai/gpt-6-luna"), baseline(), NOW)
    inputs = merged.matrix.models["openai/gpt-6-luna"].inputs
    assert inputs.accepted == ["image", "document"] and inputs.source == "baseline"
    assert inputs.attempts == {} and inputs.last_attempt_at == {}
    assert inputs.probed_at["image"] == "2026-10-30T00:00:00Z"


def test_a_baseline_unknown_kind_keeps_its_backoff():
    # claude-opus-5: document unknown in the baseline; its stored backoff must survive the merge
    stored_inputs = dict(
        accepted=["image"],
        answers={"image": 200},
        probed_at={"image": "2026-11-01T00:00:00Z"},
        retry_after={"document": "2026-11-19T00:00:00Z"},
        unanswered_rounds={"document": 0},
        attempts={"document": 2},
        last_attempt_at={"document": "2026-11-12T00:00:00Z"},
        source="probe",
    )
    current = stored(**{"anthropic/claude-opus-5": entry(**stored_inputs)})
    merged = matrix.merge(current, live("anthropic/claude-opus-5"), baseline(), NOW)
    after = merged.matrix.models["anthropic/claude-opus-5"].inputs
    assert after.retry_after == stored_inputs["retry_after"]
    assert after.unanswered_rounds == stored_inputs["unanswered_rounds"]
    assert after.attempts == stored_inputs["attempts"]
    assert after.probed_at == stored_inputs["probed_at"]
    assert after.accepted == ["image"] and "document" not in after.refused


def test_an_entry_with_its_own_answer_keeps_it():
    own = entry(
        refused={"image": 400},
        answers={"image": 400},
        probed_at={"image": "2026-11-11T00:00:00Z"},
        source="probe",
    )
    current = stored(**{"openai/gpt-6-luna": own})
    merged = matrix.merge(current, live("openai/gpt-6-luna"), baseline(), NOW)
    after = merged.matrix.models["openai/gpt-6-luna"].inputs
    assert after.refused == {"image": 400} and "image" not in after.accepted
    assert after.accepted == ["document"]  # the kind that was not attempted is filled
    assert after.source == "probe"


def test_an_attempted_kind_is_not_overwritten():
    one_round = entry(unanswered_rounds={"document": 1}, attempts={"document": 1})
    current = stored(**{"openai/gpt-6-luna": one_round})
    merged = matrix.merge(current, live("openai/gpt-6-luna"), baseline(), NOW)
    after = merged.matrix.models["openai/gpt-6-luna"].inputs
    assert "document" not in after.accepted and "document" not in after.refused
    assert after.unanswered_rounds == {"document": 1} and after.attempts == {"document": 1}
    assert after.accepted == ["image"]  # the other kind was not attempted: filled


def test_the_merge_never_modifies_its_input():
    current = stored(**{"openai/gpt-6-luna": entry()})
    before = current.model_dump_json()
    matrix.merge(current, live("openai/gpt-6-luna"), baseline(), NOW)
    assert current.model_dump_json() == before


def test_a_removed_model_keeps_its_inputs():
    current = stored(
        **{
            "v/a": entry(accepted=["image"], probed_at={"image": "x"}),
            "v/b": entry(),
        }
    )
    merged = matrix.merge(current, live("v/b", "v/c"), baseline(), NOW)
    removed = merged.matrix.models["v/a"]
    assert removed.status == "removed" and removed.inputs.accepted == ["image"]


# --- one owner -----------------------------------------------------------------------------


def test_modality_facts_have_one_owner():
    hits = []
    for path in SRC.rglob("*.py"):
        text = path.read_text()
        for number, line in enumerate(text.splitlines(), 1):
            if re.search(r"input_modalities|modalit", line):
                hits.append(f"{path.relative_to(SRC)}:{number}")
    assert all(h.startswith(("matrix.py", "tools/models.py")) for h in hits), hits
