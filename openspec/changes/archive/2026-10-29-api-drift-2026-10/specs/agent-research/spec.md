# Spec Delta

## MODIFIED Requirements

### Requirement: Runs are background and retrievable
Every research request SHALL set `background` true and `store` true, and the tool SHALL offer no way to set `store` false: the API makes a background run with `store` false unretrievable, so its result and its cost would be lost.

#### Scenario: Request shape
- **WHEN** a research run is submitted at depth `high`
- **THEN** the request has `effort` `high`, `background` true and `store` true
