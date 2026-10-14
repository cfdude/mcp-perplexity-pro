## Context

The package builds and runs (`uv build`, `uvx --from .`), with two commands (`mcp-perplexity-pro`, `perplexity-pro`) after `py-cli`. Publishing is outward-facing and not reversible (a PyPI version number can be yanked but never reused), so the design separates what can be verified offline from what needs the owner.

## Goals / Non-Goals

**Goals:** a package that installs and runs from PyPI exactly as from a checkout; a release that cannot publish a wrong version, a leaking file or a token; the first upload rehearsed on TestPyPI.

**Non-Goals:** uploading anything; choosing the license for Rob; the npm package of 1.x.

## Decisions

**D1. Names.** The distribution name stays `mcp-perplexity-pro` (free on PyPI, 404 on 2026-10-13) and it provides both commands. `perplexity-pro` is also free; it is not registered as a second distribution (one name, two commands; the name can be reserved later if someone squats it).

**D2. License is a gate, MIT is the default carried over.** The 1.x `package.json` declared `"license": "MIT"` and author Rob Sherman, and the Python repository has no `LICENSE` file. The metadata uses `license = "MIT"` (SPDX) plus `license-files = ["LICENSE"]` and a standard MIT `LICENSE` with the copyright holder `Rob Sherman`; the year is the year of the release, written when the tag is cut. The license is Rob's decision and is listed as a gate before the first tag.

**D3. Classifiers say what is true.** `Programming Language :: Python :: 3.12`, `3.13`, `3.14` (CI runs 3.12 and 3.14), `Environment :: Console`, `Topic :: Software Development :: Libraries`, `Intended Audience :: Developers`, `License :: OSI Approved :: MIT License` is not added (PEP 639 says use the SPDX field instead), `Development Status :: 4 - Beta` (2.0.0 is the first Python release and has seen one author's live use), and a keyword list (`mcp`, `perplexity`, `llm`, `search`, `cli`).

**D4. The sdist is an allowlist.** `[tool.hatch.build.targets.sdist] include` names `src`, `tests`, `README.md`, `CHANGELOG.md`, `LICENSE`, `pyproject.toml` and `uv.lock`. A `build` test lists the sdist and fails if it contains `openspec/`, `.conductor/`, `docs/`, `CLAUDE.md`, `PROJECT.md`, `ecosystem.config.cjs`, an `.env*` file or anything outside the allowlist, and that the wheel holds the migrations and both entry points (the existing wheel tests stay).

**D5. README on PyPI.** PyPI renders the README as the project page; relative links (`openspec/...`, `docs/...`) break there. The README is not rewritten for PyPI; instead the few relative links are made absolute `https://github.com/cfdude/mcp-perplexity-pro/blob/main/...` URLs, and a test fails on a relative Markdown link to a path that is not shipped in the sdist (links to `README` anchors are fine).

**D6. One release workflow, two triggers, no token.** `release.yml`: `on: push: tags: ['v*']` and `workflow_dispatch`. Job `build` (permissions `contents: read`): checkout, `astral-sh/setup-uv`, `uv sync --locked`, the same lint and tests as CI, `uv build`, check that the tag with its leading `v` equals `project.version` (the dispatch run skips the tag check), `uvx twine check dist/*`, install the wheel into a clean environment with `uv run --isolated --no-project --with dist/*.whl` and run `mcp-perplexity-pro --version` and `perplexity-pro help ask`, upload `dist/` as an artifact. Job `publish-pypi` (`needs: build`, `if` tag push, `environment: pypi`, permissions `id-token: write` only) downloads the artifact and uses `pypa/gh-action-pypi-publish` with no `password`. Job `publish-testpypi` (`if` dispatch, `environment: testpypi`, same permissions, `repository-url: https://test.pypi.org/legacy/`). Actions are pinned to a major version, as in CI. A test parses the workflow file and fails if any `secrets.` reference, a `password:` input, or `id-token: write` outside the two publish jobs exists, or if `environment:` is missing on them.

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
