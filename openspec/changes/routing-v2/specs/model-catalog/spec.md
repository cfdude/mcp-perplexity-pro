# Spec Delta

## MODIFIED Requirements

### Requirement: Active routing is reported
`perplexity_models` SHALL include a `routing` section stating the active mode, the standard model or the three tiers with what each runs (a model id; in `dynamic` mode an unpinned tier has a null id, meaning the router chooses, and no `preset` field exists any more), and whether the live catalog lists each model id (`known`; null when the id is null). In `dynamic` mode it SHALL also name the classifier in use (`rules` unless another is configured) and carry one `evidence` line (see `routing-evidence`). The section describes configuration and SHALL be present whatever the `provider` filter is.

#### Scenario: Standard routing section
- **WHEN** a client calls `perplexity_models` against a default server
- **THEN** the result's routing section has mode `standard` and model `perplexity/sonar` with `known` true when the live catalog lists it

#### Scenario: Custom routing section
- **WHEN** the server runs in `custom` mode and one tier model is not in the catalog
- **THEN** the section lists the three tiers and marks that one `known` false

#### Scenario: Dynamic routing section
- **WHEN** a client calls `perplexity_models` against a `dynamic` server with no tier variables set
- **THEN** the section has mode `dynamic`, classifier `rules`, the three tiers with null ids, and an `evidence` line holding the `as_of`, the shortlist size and the eligible count for each of `coding`, `reasoning` and `browsing`

#### Scenario: A pinned tier
- **WHEN** `PERPLEXITY_TIER_COMPLEX` pins a model
- **THEN** the section shows that model for `complex` with its `known` flag and null ids for the other tiers

#### Scenario: Catalog unreadable
- **WHEN** the catalog cannot be fetched and no cache exists
- **THEN** the call fails as it does today (the other three channels still carry the routing); with a stale cache the section is built from it and the existing staleness notice applies

#### Scenario: An unlisted id is still used
- **WHEN** a configured model id is `known` false
- **THEN** calls still send it as configured, because the catalog can lag and a typo is reported by the API on the first call

## ADDED Requirements

### Requirement: The held listing is readable without a fetch
The catalog SHALL expose the live model ids of the listing it already holds in memory (none when it holds none) without making a request, so that selection never adds a network call. A forced refresh SHALL read only the API's own models listing and SHALL NOT read or scrape documentation.

#### Scenario: No listing held
- **WHEN** the process has not fetched a listing and the selector asks for the live ids
- **THEN** it receives none, makes no request, and applies no listing filter

#### Scenario: Listing held
- **WHEN** a listing is held that lacks a shortlist id
- **THEN** the accessor omits that id and no request is made

#### Scenario: Only the API listing
- **WHEN** a forced refresh runs
- **THEN** the only request it makes is the models listing endpoint already used by the catalog
