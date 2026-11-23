-- Long-term memory (docs/07_MEMORY_PLAN.md, Part B). Memories exist only because the user added or confirmed them;
-- 'pending' rows are suggestions waiting for Keep/Dismiss and are never used in answers.
CREATE TABLE IF NOT EXISTS memories (
    memory_id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    text VARCHAR(300) NOT NULL,
    kind VARCHAR(12) NOT NULL CHECK (kind IN ('fact', 'preference', 'conclusion')),
    origin VARCHAR(10) NOT NULL CHECK (origin IN ('manual', 'suggested')),
    status VARCHAR(10) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'pending')),
    embedding vector(384),
    source_conversation_id UUID REFERENCES conversations(conversation_id) ON DELETE SET NULL,
    source_message_id UUID REFERENCES messages(message_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    use_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS memories_user_idx ON memories(user_id, status);

CREATE TABLE IF NOT EXISTS user_memory_settings (
    user_id UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT true,   -- use memories and past chats in answers
    suggest BOOLEAN NOT NULL DEFAULT true    -- let PKOS propose memories (each still confirmed by the user)
);

-- Past chats (episodic memory): a recap per chat and its embedding.
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS recap TEXT;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS recap_embedding vector(384);
-- The memories given to the model for an answer, shown again when the chat is reopened.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS memories_used JSONB;
