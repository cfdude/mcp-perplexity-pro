## Purpose

Defines the local store of embedding chunks: the table and its migration, how its rows are tied to projects, chats and research jobs, uniqueness, chunking and the size cap.

## ADDED Requirements

### Requirement: Chunk table and migration
Migration `0005` SHALL create `embedding_chunks` with the columns of the design (`project_id`, `source`, `chat_message_id`, `research_job_id`, `ref`, `chunk_index`, `text`, `text_hash`, `model`, `dimensions`, `encoding`, `vector`, `created_at`), keep the migration conventions (working `downgrade`, backup before upgrading, refusal of a newer database), and the ORM model SHALL match the migrated schema.

#### Scenario: Upgrade and downgrade
- **WHEN** the database is at `0004` and the server starts, and then `0005` is downgraded
- **THEN** the table is created with a backup `backup-0004.db` first, and dropped by the downgrade with every other table untouched

#### Scenario: Model matches schema
- **WHEN** the ORM model and the migrated table are compared
- **THEN** their columns, keys, indexes and constraints agree

### Requirement: Rows are tied to their source
A chunk SHALL belong to a project (`ON DELETE CASCADE`) and, by its `source`, to exactly one of a chat message (`chat`, `ON DELETE CASCADE`), a research job (`job`, `ON DELETE CASCADE`) or a caller key (`text`); the database SHALL refuse a row whose `source` and keys disagree. Deleting a chat, a job or a project SHALL delete its chunks.

#### Scenario: Cascades
- **WHEN** a chat with indexed messages is deleted, and separately a research job, and separately a project
- **THEN** the chunks of that chat's messages, that job and that project are gone and others remain

#### Scenario: Inconsistent row refused
- **WHEN** a row has source `chat` and no message id, or source `text` and a job id
- **THEN** the insert is refused

### Requirement: Chunks are unique per model triple
A chunk SHALL be unique per `(project, ref, chunk_index, model, dimensions, encoding)`, so the same text embedded with another model, size or encoding is a separate row and the same triple never stores a chunk twice.

#### Scenario: Same text two models
- **WHEN** one message is indexed with the 0.6b model and again with the 4b model
- **THEN** both sets of chunks exist and neither replaces the other

#### Scenario: Duplicate insert ignored
- **WHEN** the same chunk key is inserted twice
- **THEN** one row exists

### Requirement: Chunking
A text SHALL be split into chunks of at most 4000 characters at the last blank line, else line break, else space before the limit, else at the limit; chunks SHALL be stripped, empty ones dropped, and at most 50 chunks kept per text with a warning. The split SHALL be deterministic.

#### Scenario: Short and long text
- **WHEN** a 100-character text, and separately a 9000-character text of 100-character lines, are chunked
- **THEN** the first is one chunk and the second chunks of at most 4000 characters ending at line breaks, joined with nothing lost but whitespace

#### Scenario: Unbroken text and the chunk cap
- **WHEN** a 5000-character text with no whitespace, and separately a text needing 51 chunks, are chunked
- **THEN** the first splits at 4000 characters and the second keeps 50 chunks and reports the cut

### Requirement: Stored-chunk cap
A project SHALL hold at most 20000 chunks per `(model, dimensions, encoding)`. An `index` that would exceed it SHALL fail with `invalid_request` before any upstream call.

#### Scenario: Cap reached
- **WHEN** a project holds 20000 chunks for a triple and another chunk is to be added
- **THEN** the call fails with `invalid_request` and nothing is sent
