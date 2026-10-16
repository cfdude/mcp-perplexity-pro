// Example pm2 configuration. Copy to ecosystem.config.cjs (gitignored), replace REPLACE_ME with
// the real Perplexity API key in the copy, adjust `cwd` and `script`, then:
//   pm2 start ecosystem.config.cjs
// Never put a real key in this example file.
module.exports = {
  apps: [
    {
      name: 'mcp-perplexity-pro',
      script: 'uv', // use the absolute path from `which uv` if pm2 cannot find it
      args: 'run --frozen mcp-perplexity-pro --transport http',
      cwd: __dirname,
      interpreter: 'none',
      instances: 1,
      exec_mode: 'fork',
      watch: false,
      env: {
        PERPLEXITY_API_KEY: 'REPLACE_ME',
        PERPLEXITY_HOST: '127.0.0.1',
        PERPLEXITY_PORT: '8102',
        PERPLEXITY_LOG_LEVEL: 'INFO',
        // Optional routing (README: "Choosing how models are picked"). Defaults: standard mode,
        // model perplexity/sonar. For custom mode set all three tiers; 'dynamic' needs no tiers (optional overrides).
        // PERPLEXITY_ROUTING: 'standard',
        // PERPLEXITY_MODEL: 'perplexity/sonar',
        // PERPLEXITY_TIER_LIGHT: 'openai/gpt-6-luna',
        // PERPLEXITY_TIER_STANDARD: 'perplexity/sonar',
        // PERPLEXITY_TIER_COMPLEX: 'anthropic/claude-sonnet-5-5',
      },
      // Logging
      log_file: './logs/mcp-perplexity-pro.log',
      error_file: './logs/mcp-perplexity-pro-error.log',
      out_file: './logs/mcp-perplexity-pro-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      // Restart behavior
      autorestart: true,
      restart_delay: 4000,
      max_restarts: 10,
      min_uptime: '10s',
      max_memory_restart: '500M',
      kill_timeout: 15000, // must exceed the server's 10 s in-flight shutdown bound
      wait_ready: false,
    },
  ],
};
