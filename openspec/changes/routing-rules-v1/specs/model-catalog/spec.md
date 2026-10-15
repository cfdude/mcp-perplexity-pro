# Spec Delta

## MODIFIED Requirements

### Requirement: Active routing is reported
`perplexity_models` SHALL include a `routing` section stating the active mode, the standard model or the three tiers with what each runs (a model id, or a preset name for a dynamic tier that runs a preset), and for each configured model id whether the live catalog this call read lists it (`known` true or false; a preset entry has no id and `known` null). In `dynamic` mode it SHALL also name the classifier (`rules`). The section describes configuration and SHALL be present whatever the `provider` filter is.

#### Scenario: Standard routing section
- **WHEN** a client calls `perplexity_models` against a default server
- **THEN** the result's routing section has mode `standard` and model `perplexity/sonar` with `known` true when the live catalog lists it

#### Scenario: Custom routing section
- **WHEN** the server runs in `custom` mode and one tier model is not in the catalog
- **THEN** the section lists the three tiers and marks that one `known` false

#### Scenario: Dynamic routing section
- **WHEN** a client calls `perplexity_models` against a `dynamic` server with no tier variables set
- **THEN** the section has mode `dynamic`, classifier `rules`, `light` as preset `fast`, `standard` as model `perplexity/sonar` with `known`, and `complex` as preset `medium`

#### Scenario: Catalog unreadable
- **WHEN** the catalog cannot be fetched and no cache exists
- **THEN** the call fails as it does today (the other three channels still carry the routing); with a stale cache the section is built from it and the existing staleness notice applies

#### Scenario: An unlisted id is still used
- **WHEN** a configured model id is `known` false
- **THEN** calls still send it as configured, because the catalog can lag and a typo is reported by the API on the first call
