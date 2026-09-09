CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
CREATE TABLE IF NOT EXISTS documents (
    bucket text NOT NULL,
    id text NOT NULL,
    body jsonb NOT NULL,
    PRIMARY KEY (bucket, id)
);
CREATE TABLE IF NOT EXISTS knowledge_nodes (
    id text PRIMARY KEY,
    repository text NOT NULL,
    kind text NOT NULL,
    body text NOT NULL,
    source_ref text NOT NULL,
    revision text NOT NULL,
    properties jsonb NOT NULL DEFAULT '{}',
    embedding public.vector
);
CREATE TABLE IF NOT EXISTS knowledge_edges (
    source text NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    target text NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    kind text NOT NULL,
    PRIMARY KEY(source,target,kind)
);
CREATE INDEX IF NOT EXISTS knowledge_repository ON knowledge_nodes(repository);
CREATE INDEX IF NOT EXISTS knowledge_body ON knowledge_nodes
    USING gin(to_tsvector('simple',body));
