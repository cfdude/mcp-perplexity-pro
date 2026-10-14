## 0. Before apply

- [ ] 0.1 Record Gate 1 (`record-gate-review pypi-publish --gate 1 --verdict pass --base-sha <a> --head-sha <b> --reviewer ... --artifact openspec/changes/pypi-publish`) after a fresh-context review, and the release cross-spec review (`record-cross-spec-review release-2-0-0`); ORDER: before group 1 and again after any amendment

## 1. Metadata and distributions

- [ ] 1.1 RED then GREEN: `LICENSE` (MIT, `Rob Sherman`, the release year), `pyproject.toml` metadata (SPDX `license` and `license-files`, authors, keywords, classifiers per design D3, `[project.urls]`, readme content type) and `[tool.hatch.build.targets.sdist] include` (design D4); tests `tests/test_package_metadata.py` (offline: parse `pyproject.toml` and assert every field; README relative links all point at shipped paths, which turns the existing relative links into absolute GitHub URLs where they point outside the allowlist) and a `build`-marker test `tests/test_distributions.py` (build both; sdist paths all inside the allowlist and none of the forbidden patterns; wheel METADATA fields; LICENSE in both; entry points and migrations in the wheel); mutation-check: add `openspec` to the sdist include and confirm red

## 2. Release workflow

- [ ] 2.1 RED then GREEN: `.github/workflows/release.yml` per design D6; `tests/test_release_workflow.py` parses it with `yaml` (add `pyyaml` to the dev group if absent) and asserts: triggers, no `secrets.` and no `password`, `id-token: write` only on the two publish jobs, each has `environment` and `needs: build`, `if` conditions separate tag and dispatch, the tag-equals-version step exists and the dispatch run skips it, the lint, test, `twine check` and clean-install steps exist, action versions are pinned to a major; verify the tag check script offline by running its shell body against a fake tag; mutation-check: add `password: ${{ secrets.X }}` and confirm red

## 3. Documentation

- [ ] 3.1 README: install and run from PyPI (`uvx mcp-perplexity-pro`, `uvx --from mcp-perplexity-pro perplexity-pro ...`, `uv tool install`, `pipx install`, an MCP client configuration using `uvx`, still showing the checkout path for developers); `docs/releasing.md` (design D8 setup with exact names, checklist, tag command, yank); CHANGELOG note that 2.0.0 is a Python package and that the 1.x npm package is not updated; `CLAUDE.md` (the non-goal "PyPI publishing" line, the module/ops notes, the current-change pointer) keeping the pm-managed block byte-identical; verify the commands in the README against a clean-environment run of the built wheel

## 4. Acceptance (offline and local)

- [ ] 4.1 Build both distributions and list them; run `uvx twine check`; run the built wheel in a clean environment (`uv run --isolated --no-project --with dist/<wheel> mcp-perplexity-pro --version` and `perplexity-pro help ask`, which needs the package index for dependencies); record sizes and outputs under `openspec/changes/pypi-publish/acceptance/`; nothing is uploaded

## 5. Gate procedure (required, per the pm conductor)

- [ ] 5.1 Call-site completeness sweep: for every rule this change introduces (the sdist allowlist, license and metadata, the workflow safety rules, the README links) enumerate all call sites mechanically with `rg` (every `permissions:` and `id-token` in `.github/workflows/`, every relative link in README, every file under the repository root that the allowlist excludes or includes, every place the version appears: `pyproject.toml`, `CHANGELOG.md`, docs) and state where each rule holds and where not, with the justification; include the inverses (a release that can be made must be yankable: documented; a TestPyPI rehearsal that can publish must not be able to reach PyPI)
- [ ] 5.2 Verify against each task's commit, not the working tree: for every task above run `git show --stat <sha>` and assert each file the task claims to change appears in that commit
- [ ] 5.3 Attribute every commit of this change to its epic with `update-epic pypi-publish --attribute-commit <sha>` as each lands, in landing order; never attribute the archive move, the pm bookkeeping commits or an ancestor after a later commit; verify the last attributed commit is the Gate 2 head
- [ ] 5.4 Route what the work taught: practices, tooling friction and process lessons, each named as one of those three kinds; write `openspec/changes/pypi-publish/routing.md` with exactly three lines `practice: ...`, `tooling: ...` and `process: ...`, each naming the filed item or reading `none, because <reason that names the command or commit checked>`
- [ ] 5.5 Gate 2 implementation and documentation review by a fresh-context reviewer over the full committed range, fix Critical and Important findings, then `record-gate-review pypi-publish --gate 2 --verdict pass --base-sha <a> --head-sha <b>`; verify the verdict reaches the last attributed commit

## 6. Owner gates (not done by the build; the change stays open until they are)

- [ ] 6.1 Rob confirms the license (MIT, carried over from the 1.x declaration) and configures the pending Trusted Publishers on pypi.org and on test.pypi.org (repository `cfdude/mcp-perplexity-pro`, workflow `release.yml`, environments `pypi` and `testpypi`; `docs/releasing.md` has the exact steps)
- [ ] 6.2 TestPyPI rehearsal: run the release workflow manually (`gh workflow run release.yml`), then verify with `uvx --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ --from mcp-perplexity-pro mcp-perplexity-pro --version` and `perplexity-pro help ask`; record the outputs under `acceptance/`
- [ ] 6.3 Release: set the `[2.0.0]` date in `CHANGELOG.md` and the license year, merge to `main`, tag `v2.0.0`, push the tag, watch the workflow, then verify `uvx mcp-perplexity-pro --version` from PyPI and record it under `acceptance/`

## 7. Archive

- [ ] 7.1 Archive the change and record the disposition (`update-epic pypi-publish --status archived --outcome delivered --no-deferrals`) after group 6; verify `openspec list` no longer shows it and `PROJECT.md` renders it archived; then archive the `python-rewrite-2-0` umbrella epic as Rob decided on 2026-10-13 <!-- pm:lifecycle -->
