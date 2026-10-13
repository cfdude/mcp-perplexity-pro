## ADDED Requirements

### Requirement: Active routing is reported
`perplexity_models` SHALL include a `routing` section stating the active mode, the standard model or the three tiers with their model ids, and for each configured id whether the live catalog lists it (`known` true or false, or null when the catalog could not be read). The section describes configuration and SHALL be present whatever the `provider` filter is.

#### Scenario: Standard routing section
- **WHEN** a client calls `perplexity_models` against a default server
- **THEN** the result's routing section has mode `standard` and model `perplexity/sonar` with `known` true when the live catalog lists it

#### Scenario: Custom routing section
- **WHEN** the server runs in `custom` mode and one tier model is not in the catalog
- **THEN** the section lists the three tiers and marks that one `known` false

#### Scenario: Catalog unreadable
- **WHEN** the catalog cannot be fetched and no cache exists
- **THEN** the call fails as it does today; with a stale cache the section is built from it and the existing staleness notice applies

#### Scenario: An unlisted id is still used
- **WHEN** a configured model id is `known` false
- **THEN** calls still send it as configured, because the catalog can lag and a typo is reported by the API on the first call
