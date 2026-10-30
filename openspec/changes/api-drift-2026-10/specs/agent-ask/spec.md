# Spec Delta

## ADDED Requirements

### Requirement: Agent requests name the preset as effort
Every Agent API request the server builds (an ask, a chat send, a research submit) SHALL name its preset in the body field `effort` and SHALL NOT send `preset`, which the API keeps only as a deprecated alias. Wherever the Agent specs say a request names a preset, this field is meant. The preset names (`fast`, `low`, `medium`, `high`, `xhigh`) and the tools' `depth` arguments are unchanged.

#### Scenario: An ask at a depth
- **WHEN** a client asks with `depth` `medium`
- **THEN** the request body has `effort` `medium` and no `preset` key

#### Scenario: A research submit
- **WHEN** a client submits research at its default depth
- **THEN** the background request has `effort` equal to that depth and no `preset` key

#### Scenario: A chat send at a depth
- **WHEN** a chat send names `depth` `fast`
- **THEN** its request has `effort` `fast` and no `preset` key

### Requirement: Versioned effort values in responses are read as before
A response whose `effort` and `preset` fields carry a versioned value (such as `fast@2026-10-16.0`) SHALL be digested, stored and recorded exactly as one that names the plain preset: the preset recorded on usage events and chat turns is the name the request asked for, not the response's value.

#### Scenario: A versioned response
- **WHEN** an ask at `depth` `fast` receives a response whose `effort` and `preset` are `fast@2026-10-16.0`
- **THEN** the result is digested as before, the usage event records preset `fast`, and a later chat follow-up still recovers its tier from the stored preset
