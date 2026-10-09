# Spec Delta

## MODIFIED Requirements

### Requirement: Configuration from environment
The server SHALL read configuration from environment variables with the prefix `PERPLEXITY_` and validate it at startup. `PERPLEXITY_API_KEY` is required. These are optional with documented defaults: `HOST`, `PORT`, `BASE_URL`, `DATA_DIR`, `LOG_LEVEL`, `CONNECT_TIMEOUT`, `READ_TIMEOUT`, `AGENT_READ_TIMEOUT`, `MAX_ATTEMPTS`, `MAX_RETRY_WAIT`, `CATALOG_TTL`, `CATALOG_MAX_STALE` and `DB_BUSY_TIMEOUT`. Invalid values SHALL abort startup with a message naming the variable.

#### Scenario: Documented defaults
- **WHEN** only `PERPLEXITY_API_KEY` is set
- **THEN** the settings are host `127.0.0.1`, port 8102, base URL `https://api.perplexity.ai`, data directory `~/.perplexity-pro/`, log level INFO, connect timeout 10 s, read timeout 60 s, agent read timeout 120 s, 3 attempts, 30 s maximum retry wait, catalog TTL 3600 s, maximum stale age 86400 s and database busy timeout 5 s

#### Scenario: Missing API key
- **WHEN** the server starts without `PERPLEXITY_API_KEY`
- **THEN** startup fails with a message naming `PERPLEXITY_API_KEY` and the process exits non-zero before accepting any connection

#### Scenario: Invalid port
- **WHEN** the port variable is set to a non-integer
- **THEN** startup fails with a message naming that variable and the offending value

#### Scenario: Agent read timeout override
- **WHEN** `PERPLEXITY_AGENT_READ_TIMEOUT` is set to 240, and separately to `0` or `soon`
- **THEN** the first starts with an agent read timeout of 240 s, and each of the others fails startup with a message naming `PERPLEXITY_AGENT_READ_TIMEOUT` and the offending value
