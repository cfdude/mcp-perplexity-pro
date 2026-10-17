# Spec Delta

## ADDED Requirements

### Requirement: Matrix settings
`PERPLEXITY_MATRIX_REFRESH` SHALL be a whole number of seconds from 0 to 604800 (default 86400, 0 meaning only at start) and `PERPLEXITY_MATRIX_PROBE` SHALL be `new` (default) or `off`, case-insensitive; a bad value SHALL fail startup naming the variable. The refresh task starts after the listener is ready and SHALL NOT delay it.

#### Scenario: Defaults
- **WHEN** the server starts with only the API key
- **THEN** the refresh interval is 86400 seconds and probing is `new`

#### Scenario: A bad value
- **WHEN** `PERPLEXITY_MATRIX_PROBE=sometimes`
- **THEN** startup fails naming `PERPLEXITY_MATRIX_PROBE` and the accepted values
