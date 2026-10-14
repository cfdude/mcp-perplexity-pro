---
name: restart-pm2-from-the-ecosystem-file
kind: process-failure
trigger: Restarting the live pm2 app `mcp-perplexity-pro` to load new code (a live acceptance run, a deploy).
cost: In routing-modes-config, `pm2 restart mcp-perplexity-pro --update-env` replaced the app's environment with the shell's. The shell held a different `PERPLEXITY_API_KEY` from the one in the gitignored `ecosystem.config.cjs`, so the server started, passed `/health`, and answered every upstream call with `authentication`. A plain `pm2 restart` kept the wrong environment. Found only because the first live tool call failed; fixed with `pm2 restart ecosystem.config.cjs --update-env`, verified by comparing a hash of the process's key with the file's (never printing either).
enforced_in: the 5.1 task of routing-modes-config (restart, then make one authenticated call before counting the restart as verified) and this lesson; `/health` alone proves nothing about the key.
---

Restart this app from its ecosystem file (`pm2 restart ecosystem.config.cjs --update-env`), never by
name with `--update-env`, because the name form takes the calling shell's variables. After any
restart make one call that uses the key (`perplexity_models` is cheapest) before the restart counts
as verified. To compare keys without printing them, hash each: `ps eww -p $(pm2 pid mcp-perplexity-pro)`
for the process, the file's value for the other, then `shasum`.
