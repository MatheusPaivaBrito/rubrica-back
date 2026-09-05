# Core/Eventing Contract

Core owns business commands and query routes. Eventing owns event intake,
outbox state, schemas and optional Kafka publication.

Core should enqueue business events through this contract instead of writing
directly to Eventing internals.
