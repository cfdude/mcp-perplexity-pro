# Acceptance record, pypi-publish (2026-10-13), nothing uploaded

Local only: the distributions were built, inspected and run; no request was made to PyPI or TestPyPI (those are the owner's gates, tasks 6.1 to 6.3).

- `dist-listing.txt`: `uv build` produced `mcp_perplexity_pro-2.0.0.tar.gz` (663577 bytes, 426 files; it was about 1 MB with the project-management directories) and `mcp_perplexity_pro-2.0.0-py3-none-any.whl` (190365 bytes).
- `twine-check.txt`: `twine 7.0.0 check` PASSED for both files (the PEP 639 `License-Expression` metadata is accepted).
- `clean-install-version.txt`, `clean-install-help.txt`: the built wheel run in a clean environment with `uv run --isolated --no-project --with <wheel>` from an empty directory: `mcp-perplexity-pro --version` prints `2.0.0` and `perplexity-pro help ask` prints the tool page (the dependencies came from the package index).
- The sdist contents are pinned by `tests/test_distributions.py` (anchored allowlist plus `.gitignore` and `PKG-INFO`) and the wheel's metadata, entry points and migrations by the same file.
