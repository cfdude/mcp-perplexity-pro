# Spec Delta

## MODIFIED Requirements

### Requirement: The classifier runs only when it is needed
The classifier SHALL run only for a call in dynamic mode with the Decisions classifier that names no `depth`, `tier` or `model` and whose options and project name validated, and for research never (research is classified by the rules alone, so a research submit makes no Decisions request). A call with `search` false is classified like any other, because every router route is a model route. An invalid call makes no Decisions request.

#### Scenario: Explicit selector
- **WHEN** a call in this mode names `depth` `fast`
- **THEN** no Decisions request is made

#### Scenario: Invalid call
- **WHEN** a call in this mode has an invalid option
- **THEN** it fails as it does today and no Decisions request is made

#### Scenario: Search off
- **WHEN** a call in this mode has `search` false
- **THEN** the Decisions request is made as for any nameless call and the routed model runs without tools

#### Scenario: Unknown chat
- **WHEN** a nameless follow-up names a chat that does not exist, or one with no stored response and `replay` false
- **THEN** it fails as it does today and no Decisions request is made

#### Scenario: Floor already complex
- **WHEN** the chat's last turn ran `complex` and the follow-up names nothing
- **THEN** no Decisions request is made and the follow-up runs `complex`

#### Scenario: Follow-up floor
- **WHEN** the chat's last turn ran `standard` and the Decisions classifier answers `light` for the follow-up
- **THEN** the follow-up runs at tier `standard`

#### Scenario: Router refusals come first
- **WHEN** a nameless call in this mode would be refused by the router (no model accepts a required modality)
- **THEN** it fails before any Decisions request is made

### Requirement: The classifier field says who supplied the tier
The routing `classifier` SHALL be `decisions` when the Decisions tier was used (confident, or weak and not lower than the rules' tier) and `rules` when the rules supplied the tier (a failure, or weak and lower). A held follow-up floor does not change it, and a call whose tier was named by the caller (`selected_by` `tier`) has `classifier` null because nothing classified its tier.

#### Scenario: Decisions decided
- **WHEN** the answer is `complex` with probability 0.91
- **THEN** the routing has `classifier` `decisions` and a reason naming `complex` and the probability

#### Scenario: Rules supplied the tier
- **WHEN** the Decisions request fails with `rate_limited`
- **THEN** the routing has `classifier` `rules` and a reason naming `rate_limited` and the rules' own reason, within 120 characters

#### Scenario: Floor held over a Decisions answer
- **WHEN** a follow-up's Decisions answer is `light` and the chat last ran `standard`
- **THEN** the tier is `standard`, `classifier` is `decisions` and the reason says the tier was held
