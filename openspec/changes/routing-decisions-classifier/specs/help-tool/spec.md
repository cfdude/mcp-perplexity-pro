# Spec Delta

## ADDED Requirements

### Requirement: The routing topic names the classifier
On a `dynamic` server the `routing` topic SHALL name the classifier in use and, for `decisions`, that it is one billed Decisions request per nameless call with a 3-second bound and that the rules replace it on failure. The topic keeps its 3000-byte limit.

#### Scenario: Decisions topic
- **WHEN** a client asks for topic `routing` on a `dynamic` server with the Decisions classifier
- **THEN** the text says the tier is picked by a Decisions request, that it is bounded and falls back to the rules, and is at most 3000 bytes
