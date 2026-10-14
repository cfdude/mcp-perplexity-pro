# Releasing to PyPI

The package is `mcp-perplexity-pro` on PyPI (it provides two commands: `mcp-perplexity-pro`, the
MCP server, and `perplexity-pro`, the command line). A release is a pushed tag `v<version>` that
`.github/workflows/release.yml` turns into an upload through **Trusted Publishing**: PyPI trusts
that workflow file in this repository (OpenID Connect), so no token or password exists anywhere.

## One-time setup (the owner does this; nothing in the repository can)

1. **GitHub environments.** In the repository settings create two environments:
   - `pypi`, with yourself as a required reviewer (a tag push then waits for your approval).
   - `testpypi`, no reviewers needed.
   A missing environment is created unprotected on first use, so create them first.
2. **A pending Trusted Publisher on pypi.org.** Sign in, open *Your projects, Publishing*, add a
   pending publisher: project name `mcp-perplexity-pro`, owner `cfdude`, repository
   `mcp-perplexity-pro`, workflow file `release.yml`, environment `pypi`.
3. **The same on test.pypi.org** (a separate account and site): project name `mcp-perplexity-pro`,
   owner `cfdude`, repository `mcp-perplexity-pro`, workflow file `release.yml`, environment
   `testpypi`.
4. Confirm the license (`LICENSE`, MIT, carried over from the 1.x `package.json`) and the
   copyright year in `LICENSE`.

## Checklist before a tag

- [ ] `main` has the release commit and CI is green on Python 3.12 and 3.14.
- [ ] `CHANGELOG.md` has the release date on the `[<version>]` heading, and `pyproject.toml` has the
      same version.
- [ ] The TestPyPI rehearsal below succeeded and the printed version and `help ask` output look right.

## Rehearse on TestPyPI

Run the workflow by hand (it publishes `<version>.dev<run number>` to TestPyPI, never the release
version, because an index refuses a second upload of the same file name):

```bash
gh workflow run release.yml
gh run watch
```

Then install it from TestPyPI and run both commands (dependencies still come from PyPI):

```bash
uvx --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ \
  --from mcp-perplexity-pro mcp-perplexity-pro --version
uvx --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ \
  --from mcp-perplexity-pro perplexity-pro help ask
```

## Release

```bash
git switch main && git pull
git tag v2.0.0            # v + the version in pyproject.toml
git push origin v2.0.0
```

The workflow checks that the tag equals the package version, repeats lint, the test suite and the
build tests, builds both distributions, runs `twine check`, installs the built wheel in a clean
environment and runs both commands, then waits for you to approve the `pypi` environment and
publishes. Afterwards verify from a clean directory:

```bash
uvx mcp-perplexity-pro --version
uvx --from mcp-perplexity-pro perplexity-pro help ask
```

## If a release is bad

A PyPI file name can never be reused. *Yank* the release on pypi.org (the project's Manage page,
Releases, Options, Yank): installers skip a yanked version unless it is pinned exactly. Fix the
problem, bump the version (`2.0.1`), and release again.
