# Call-site sweep and commit verification (tasks 5.1 and 5.2)

Derived with `rg`; the Gate 2 reviewer confirms it over the range.

| Rule | Sites | Holds |
|---|---|---|
| sdist is an anchored allowlist | `[tool.hatch.build.targets.sdist] include` (7 anchored entries); `tests/test_distributions.py` lists the built sdist; mutation (`README.md` unanchored) goes red | yes |
| license and metadata | `pyproject.toml` (`license`, `license-files`, authors, keywords, classifiers, urls), `LICENSE`, wheel METADATA test | yes |
| no secret or token in the workflow | `rg "secrets\\." .github/` finds none; `permissions` only in `ci.yml` (`contents: read`), `security.yml` and `release.yml` (`id-token: write` only on the two publish jobs) | yes, pinned by `tests/test_release_workflow.py` |
| README links | `rg "\]\(" README.md` outside code: only absolute URLs (the new releasing link is absolute) | yes, tested |
| the version appears | `pyproject.toml` (2.0.0), `CHANGELOG.md` (`[2.0.0] - 2026-10-09`, date set at the tag), `uv.lock` (package entry), `docs/releasing.md` example `v2.0.0` | the date is the owner's gate (task 6.3) |
| inverses | a release can be yanked: `docs/releasing.md` "If a release is bad"; a TestPyPI rehearsal cannot reach PyPI: the dispatch job has `environment: testpypi` and `repository-url`, the tag job has `if: push`, a test pins both | yes |

Commit verification (`git show --stat`): 1.1 `bcdaa2b` (LICENSE, pyproject.toml, two test files), 2.1 `6fff1dc` (release.yml, pyproject.toml and uv.lock for pyyaml, test_release_workflow.py), 3.1 `791be26` (docs/releasing.md, README.md, CHANGELOG.md, CLAUDE.md, tests), 4.1 `18faad1` (acceptance) each contain the files their task claims.
