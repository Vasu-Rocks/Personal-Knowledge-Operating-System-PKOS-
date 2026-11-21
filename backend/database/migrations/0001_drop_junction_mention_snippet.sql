-- chunk_entity_junction.mention_snippet was never written (edge snippets live in relationship_mentions.snippet).
ALTER TABLE chunk_entity_junction DROP COLUMN IF EXISTS mention_snippet;
