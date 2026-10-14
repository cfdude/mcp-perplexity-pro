# Proposal

## Why

Rob wants the server published to PyPI so that someone who finds it can run it as an MCP server or as a command line with one line (`uvx mcp-perplexity-pro`, `uvx --from mcp-perplexity-pro perplexity-pro ask ...`). Today the package only has to "build and run via `uvx --from .`". Probed 2026-10-13: both `mcp-perplexity-pro` and `perplexity-pro` return 404 on PyPI (the names are free), the wheel builds (189 KB), and the source distribution is 1 MB because it ships the project-management directories (`openspec/`, `.conductor/`, `docs/`, `PROJECT.md`, `CLAUDE.md`). The package has no license file (the 1.x `package.json` declared MIT, author Rob Sherman), no classifiers, no project URLs and no release workflow. PyPI's Trusted Publishing (OpenID Connect from GitHub Actions) needs no stored token, which fits the rule that credentials never live in the repository.

## What Changes

- Complete the package metadata in `pyproject.toml`: SPDX license (`MIT`, carried over from the 1.x declaration) with a `LICENSE` file, author, keywords, classifiers (Python 3.12 and 3.14, the versions CI runs, and a Beta development status), project URLs (repository, changelog, issues), and a README that renders on PyPI (relative links rewritten to absolute ones where the page would break them).
- Trim the source distribution to an anchored allowlist (`/src`, `/tests`, `/README.md`, `/CHANGELOG.md`, `/LICENSE`, `/pyproject.toml`, `/uv.lock`, plus the `.gitignore` and `PKG-INFO` hatchling always adds; 663 KB in a probe, against 1 MB today), so project-management files do not ship; a test pins the file list and that no secret-shaped file is in it.
- Add `.github/workflows/release.yml`: on a pushed tag `v*` it builds the sdist and wheel, checks that the tag equals the package version, runs `twine check`, installs the built wheel in a clean environment and runs both commands (`--version`, `help ask`), then publishes with `pypa/gh-action-pypi-publish` using Trusted Publishing (job-level `id-token: write`, a protected `pypi` environment, no token). A manual `workflow_dispatch` run publishes to TestPyPI instead, under a computed development version (`<version>.dev<run>`, because an index refuses a re-upload of a filename), so the first upload can be rehearsed.
- Document install and run from PyPI in the README (`uvx`, `uv tool install`, `pipx`, an MCP client configuration using `uvx`), and the release procedure (`docs/releasing.md`: the one-time PyPI and TestPyPI "pending publisher" setup, the checklist, the tag command).
- Gates that are the owner's, not the build's: configuring the trusted publishers on pypi.org and test.pypi.org, approving the license, setting the release date in the changelog and pushing the first tag. This change prepares everything and stops there; nothing is uploaded by this change.
- Out of scope: Smithery, Docker, npm (the 1.x package), signing, a release-notes generator, version bumping automation.

## Capabilities

### New Capabilities

- `package-release`: the published package's metadata, the source distribution contents, the release workflow and its safety rules, and the install paths documented for users.

### Modified Capabilities

- None. `quality-gates` is untouched (the release workflow follows its `--locked` rule); the rules about secrets and pinned actions are new and owned by `package-release`.

## Impact

- **Code and files:** `pyproject.toml`, new `LICENSE`, new `.github/workflows/release.yml`, new `docs/releasing.md`, README (install and run from PyPI), `CHANGELOG.md` (release date set at tag time), a test file `tests/test_package_metadata.py` plus a `build`-marker test for the sdist, and `pyyaml` added to the dev group (`uv.lock` changes).
- **Dependencies, schema, tool surface:** none.
- **Spend:** none. No network upload happens in this change; TestPyPI and PyPI uploads are the owner's gate.
