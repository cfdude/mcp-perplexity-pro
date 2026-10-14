# package-release Specification

## Purpose
TBD - created by archiving change pypi-publish. Update Purpose after archive.

## Requirements

### Requirement: Package metadata is complete and true
`pyproject.toml` SHALL declare an SPDX `license` with a `LICENSE` file shipped in both distributions, an author, a description, keywords, Python classifiers for the versions CI runs (3.12 and 3.14), a development-status classifier, project URLs (repository, changelog, issues) and a README with a rendering content type. It SHALL NOT carry a `License ::` classifier next to the SPDX field, and its build requirement SHALL be a hatchling that emits PEP 639 license metadata (1.27 or newer).

#### Scenario: Metadata present
- **WHEN** the built wheel's METADATA is read
- **THEN** it has `License-Expression`, `Author`, `Project-URL` entries for the repository, changelog and issues, the Python 3.12 and 3.14 classifiers and a keyword list, and no `License ::` classifier

#### Scenario: License file shipped
- **WHEN** either distribution is listed
- **THEN** it contains the `LICENSE` file

### Requirement: The source distribution is an allowlist
The source distribution SHALL contain only `src/`, `tests/`, `README.md`, `CHANGELOG.md`, `LICENSE`, `pyproject.toml`, `uv.lock` (each anchored at the project root) and the `.gitignore` and `PKG-INFO` the build always adds, and SHALL NOT contain the project-management directories, any `.env` file or `ecosystem.config.cjs`.

#### Scenario: Allowlist holds
- **WHEN** the source distribution is built and listed
- **THEN** every path is under the allowlist or is `.gitignore` or `PKG-INFO`, and no path (a `README.md` in a subdirectory included) matches `openspec/`, `.conductor/`, `docs/`, `CLAUDE.md`, `PROJECT.md`, `.env` or `ecosystem.config.cjs`

### Requirement: Both commands ship in the wheel
The wheel SHALL declare the `mcp-perplexity-pro` and `perplexity-pro` entry points and contain the migrations.

#### Scenario: Entry points
- **WHEN** the wheel's `entry_points.txt` is read
- **THEN** it names `mcp_perplexity_pro.__main__:main` and `mcp_perplexity_pro.command:cli`

### Requirement: The README works on PyPI
The README SHALL NOT contain a Markdown link whose target is not an absolute `http(s)` or `mailto` URL or an anchor, and SHALL document installing and running from PyPI with `uvx`, `uv tool install` and `pipx` and an MCP client configuration that starts the server with `uvx`, naming `perplexity-pro` only through `uvx --from mcp-perplexity-pro`. The documented forms are equivalent ways to start the same server, not a count of commands.

#### Scenario: No broken relative links
- **WHEN** every Markdown link of the README is checked
- **THEN** each is an absolute URL, a `mailto` or an anchor

#### Scenario: Install paths
- **WHEN** a reader looks for how to install from PyPI
- **THEN** the README shows `uvx mcp-perplexity-pro`, `uvx --from mcp-perplexity-pro perplexity-pro`, `uv tool install` and `pipx install`

### Requirement: The release workflow checks before it publishes
`.github/workflows/release.yml` SHALL run on a pushed tag `v*` and on manual dispatch, build the distributions, run the lint, test and `build`-marker suites, refuse a tag that is not `v` plus the package version, run `twine check`, install the built wheel into a clean environment and run both commands, and only then publish. A manual dispatch SHALL publish a computed development version, never the release version.

#### Scenario: Tag must equal the version
- **WHEN** a tag `v2.0.1` is pushed while `pyproject.toml` says `2.0.0`
- **THEN** the build job fails before anything is published

#### Scenario: Dispatch goes to TestPyPI
- **WHEN** the workflow is run manually
- **THEN** only the TestPyPI job publishes, and the uploaded version is `<version>.dev<run>`, not the release version

### Requirement: The release workflow publishes without a stored credential
Publishing SHALL use Trusted Publishing: no token or password, `id-token: write` granted only to the two publish jobs, each in a named environment (`pypi` for a tag, with required reviewers; `testpypi` for dispatch). Actions SHALL be pinned to a major version, except `pypa/gh-action-pypi-publish`, which SHALL use its documented `release/v1` ref.

#### Scenario: Workflow shape
- **WHEN** the workflow file is parsed
- **THEN** there are no `secrets.` references and no `password` input, `id-token: write` appears only in the publish jobs, each of which has an `environment` and `needs` the build job

### Requirement: The release procedure is written down
`docs/releasing.md` SHALL list the one-time setup (the GitHub environments `pypi`, with required reviewers, and `testpypi`; the pending Trusted Publishers on pypi.org and test.pypi.org) with the exact repository, workflow and environment names, the checklist before a tag (suite green, changelog date, license confirmed, TestPyPI rehearsal verified with `uvx --index-url`), the tag command, and how to yank a bad release.

#### Scenario: Names match the workflow
- **WHEN** the setup section is compared with the workflow
- **THEN** the workflow file name and both environment names are the same
