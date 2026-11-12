# model-matrix Specification

## ADDED Requirements

### Requirement: A retired model forces one bounded catalog refresh
The matrix state SHALL offer `refresh_now(failed_id)` for a call that failed with an answer `matrix.model_not_served` recognises. It SHALL be single-flight, rate-limited to one listing fetch of any origin per 300 seconds per process, read only the API's own models listing, merge with the existing rules and send no probe.

#### Scenario: A vanished model becomes removed
- **WHEN** a call fails not supported and the fresh listing no longer holds the id
- **THEN** the matrix entry for that id is `removed` and the next selection skips it

#### Scenario: Rate limited
- **WHEN** a second retirement occurs 60 seconds after a refresh ran
- **THEN** no listing request is made and the existing snapshot is used

#### Scenario: Single flight
- **WHEN** five calls fail not supported at once
- **THEN** exactly one listing request is made and all five proceed

#### Scenario: An outage does not loop
- **WHEN** the listing request fails
- **THEN** the failure is recorded, the stale snapshot stays, the window is consumed and no further listing request is made for 300 seconds

#### Scenario: An outage does not empty the matrix
- **WHEN** the listing returns an empty list
- **THEN** the matrix is unchanged, as the existing merge rule says

#### Scenario: No probes, no spend
- **WHEN** a forced refresh runs and a new model appears in the listing
- **THEN** no probe request is sent by it (the scheduled refresh probes later) and no usage event is written
