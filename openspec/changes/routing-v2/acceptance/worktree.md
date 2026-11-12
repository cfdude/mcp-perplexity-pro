# Worktree and pm2 precondition (routing-v2 task 0.4)

Checked 2026-11-11, before any other task of `routing-v2` or `media-inputs`.

- Main checkout `/Users/rsherman/Servers/mcp-perplexity-pro`: branch `main` (`git branch --show-current`),
  runs the live pm2 app `mcp-perplexity-pro` (port 8102). It carries no migration `0006`
  (`rg -n 0006 src` in the worktree: no match; the versions directory ends at `0005`).
- Work tree: `/Users/rsherman/Servers/mcp-perplexity-pro/.claude/worktrees/routing-v2`, branch
  `epic/routing-v2-media-inputs`, listed by `git worktree list` next to the main checkout.
- Rule: every server, probe and harness runs from the work tree only, against a temporary
  `PERPLEXITY_DATA_DIR` (`mktemp -d`), never `~/.perplexity-pro`, never pm2, never port 8102.
- Cleanup is task 9.4 (`git worktree prune`, then `git worktree list` shows only the main checkout).
