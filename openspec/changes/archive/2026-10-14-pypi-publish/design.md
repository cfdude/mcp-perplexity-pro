## Context

The package builds and runs (`uv build`, `uvx --from .`), with two commands (`mcp-perplexity-pro`, `perplexity-pro`) after `py-cli`. Publishing is outward-facing and not reversible (a PyPI version number can be yanked but never reused), so the design separates what can be verified offline from what needs the owner.

## Goals / Non-Goals

**Goals:** a package that installs and runs from PyPI exactly as from a checkout; a release that cannot publish a wrong version, a leaking file or a token; the first upload rehearsed on TestPyPI.

**Non-Goals:** uploading anything; choosing the license for Rob; the npm package of 1.x.

## Decisions

**D1. Names.** The distribution name stays `mcp-perplexity-pro` (free on PyPI, 404 on 2026-10-13) and it provides both commands. `perplexity-pro` is also free; it is not registered as a second distribution (one name, two commands; the name can be reserved later if someone squats it).

**D2. License is a gate, MIT is the default carried over.** The 1.x `package.json` declared `"license": "MIT"` and author Rob Sherman, and the Python repository has no `LICENSE` file. The metadata uses `license = "MIT"` (SPDX) plus `license-files = ["LICENSE"]` and a standard MIT `LICENSE` with the copyright holder `Rob Sherman`; the year is the year of the release, written when the tag is cut. The license is Rob's decision and is listed as a gate before the first tag.

**D3. Classifiers say what is true.** `Programming Language :: Python :: 3.12` and `3.14` (the versions CI runs; no 3.13 classifier because it is not tested), `Environment :: Console`, `Topic :: Software Development :: Libraries`, `Intended Audience :: Developers`, no `License ::` classifier (PEP 639 says use the SPDX field instead; the build tolerates both, so a test enforces it), `Development Status :: 4 - Beta` (2.0.0 is the first Python release and has seen one author's live use), and a keyword list (`mcp`, `perplexity`, `llm`, `search`, `cli`).

**D4. The sdist is an anchored allowlist.** Probed 2026-10-13 (hatchling 1.32.4): `include` takes gitignore-style patterns, so a bare `README.md` also matches `openspec/changes/archive/*/acceptance/README.md` (8 files leaked in the probe) and a bare `src` or `tests` matches such a directory at any depth. Every entry is therefore anchored: `["/src", "/tests", "/README.md", "/CHANGELOG.md", "/LICENSE", "/pyproject.toml", "/uv.lock"]` (probe: 361 `tests/` entries, 60 wheel files, 663 KB; hatchling always adds `.gitignore` and `PKG-INFO`, which the allowlist names). The wheel still builds from that sdist. A `build` test lists the sdist and fails on anything outside the allowlist plus those two, or any path matching `openspec/`, `.conductor/`, `docs/`, `CLAUDE.md`, `PROJECT.md`, `ecosystem.config.cjs` or `.env`, and checks that the wheel holds the migrations and both entry points. The build requirement is `hatchling>=1.27` (PEP 639 license metadata: older versions silently drop `License-Expression`).

**D5. README on PyPI.** PyPI renders the README as the project page; a relative Markdown link to a file outside the sdist breaks there. Probed: the README has no relative Markdown links today (its two links are absolute and the `openspec/...` paths are backticked text), so nothing is rewritten. The risk is a new link, for example to `docs/releasing.md`, which must be an absolute `https://github.com/cfdude/mcp-perplexity-pro/blob/main/...` URL. A test fails on any `](target)` that is not `http(s)`, `mailto` or `#`, or whose path is outside the allowlist. The README names `perplexity-pro` only as `uvx --from mcp-perplexity-pro perplexity-pro ...` (the name is unregistered, so a bare `uvx perplexity-pro` could run someone else's package).

**D6. One release workflow, two triggers, no token.** `release.yml`: `on: push: tags: ['v*']` and `workflow_dispatch`. Job `build` (permissions `contents: read`): checkout, `astral-sh/setup-uv`, `uv sync --locked`, the same lint, tests and `pytest -m build` as CI on Python 3.12 (the matrix of CI covers 3.14), on a dispatch run the version is first rewritten to `<version>.dev<run_number>` (TestPyPI and PyPI refuse a re-upload of a filename, so a rehearsal must not use the real version), `uv build`, check that the tag with its leading `v` equals `project.version` (the dispatch run skips the tag check), `uvx twine==7.0.0 check dist/*.whl dist/*.tar.gz`, install the wheel into a clean environment with `uv run --isolated --no-project --with dist/*.whl` and run `mcp-perplexity-pro --version` and `perplexity-pro help ask`, upload `dist/` as an artifact. Job `publish-pypi` (`needs: build`, `if` tag push, `environment: pypi`, permissions `id-token: write` only) downloads the artifact and uses `pypa/gh-action-pypi-publish` with no `password`. Job `publish-testpypi` (`if` dispatch, `environment: testpypi`, same permissions, `repository-url: https://test.pypi.org/legacy/`). Actions are pinned to a major version, as in CI, except `pypa/gh-action-pypi-publish`, which has no major tag and is used at its documented `release/v1` branch ref. The `pypi` GitHub environment is created with required reviewers (a missing environment is created unprotected on first use), so the tag push waits for a human approval. A test parses the workflow file (PyYAML turns the key `on:` into the boolean `True`, so the test reads `data.get(True)`) and fails if any `secrets.` reference, a `password:` input, or `id-token: write` outside the two publish jobs exists, or if `environment:` is missing on them.

**D7. A tag publishes only what CI accepted.** The build job repeats lint and tests; the publish job runs only when the build job passed. The tag is created by the owner after the release commit is on `main` and the checklist in `docs/releasing.md` is done; the workflow refuses a tag that does not equal the version.

**D8. This change uploads nothing.** Everything is verified offline: metadata test, sdist and wheel inspection, the clean-environment run of the built wheel (it needs the package index for dependencies, so it is an acceptance step and a CI step, not an offline unit test), the workflow parsed by a test. The first TestPyPI run and the first tag are the owner's gates (listed in the closeout), after the trusted publishers are configured on pypi.org and test.pypi.org (repository `cfdude/mcp-perplexity-pro`, workflow `release.yml`, environments `pypi` and `testpypi`).

## Risks / Trade-offs

- **An irreversible upload of a wrong release.** Mitigation: tag equals version check, the full test suite in the release workflow, a TestPyPI rehearsal first, the owner pushes the tag.
- **A leaking file in the sdist.** Mitigation: the allowlist and the pinned file list test.
- **The README links break on PyPI.** Mitigation: absolute links and a test.
- **The license is assumed.** Mitigation: it is a named gate, carried over from the owner's own 1.x declaration.
- **Trusted Publishing misconfiguration** (a wrong workflow or environment name makes the upload fail, not leak). Mitigation: the exact names are in `docs/releasing.md` and in the workflow.

## Migration Plan

None for users of a checkout. Users of 1.x (npm) are told in the CHANGELOG that 2.0.0 is a Python package.

## Open Questions

None blocking the build; the gates above need the owner.
