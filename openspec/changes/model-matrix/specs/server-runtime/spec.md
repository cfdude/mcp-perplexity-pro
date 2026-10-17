# Spec Delta

## ADDED Requirements

### Requirement: Matrix settings
`PERPLEXITY_MATRIX_REFRESH` SHALL be a whole number of seconds, 0 (only at start) or from 300 to 604800 (default 86400) and `PERPLEXITY_MATRIX_PROBE` SHALL be `new` (default) or `off`, case-insensitive; a bad value SHALL fail startup naming the variable. The refresh task is started by the server in a serving process, is never awaited by startup, and logs one line at start naming the settings and the matrix origin.

#### Scenario: Defaults
- **WHEN** the server starts with only the API key
- **THEN** the refresh interval is 86400 seconds and probing is `new`

#### Scenario: A refresh interval below the floor
- **WHEN** `PERPLEXITY_MATRIX_REFRESH=60`
- **THEN** startup fails naming `PERPLEXITY_MATRIX_REFRESH` and the accepted range

#### Scenario: A bad value
- **WHEN** `PERPLEXITY_MATRIX_PROBE=sometimes`
- **THEN** startup fails naming `PERPLEXITY_MATRIX_PROBE` and the accepted values
