-- Saved chats (docs/07_MEMORY_PLAN.md, Part A). user_id lives only on conversations: every read of messages goes
-- through the owning conversation, so a message can never be reached with another user's conversation id.
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL DEFAULT 'New chat',
    summary TEXT,                                  -- running summary of the turns outside the history window
    summary_upto_seq INTEGER NOT NULL DEFAULT 0,   -- messages with seq <= this are covered by summary
    message_count INTEGER NOT NULL DEFAULT 0,      -- also the last seq used
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS conversations_user_updated_idx ON conversations(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    message_id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    role VARCHAR(10) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    standalone_query TEXT,                         -- user messages: the question that was actually searched
    needs_search BOOLEAN,
    sources JSONB,                                 -- assistant: snapshot of the passages shown (survives document deletion)
    graph JSONB,                                   -- assistant: graph nodes/links shown in the X-Ray panel
    status VARCHAR(12) NOT NULL DEFAULT 'complete' CHECK (status IN ('complete', 'partial', 'error')),
    provider VARCHAR(20),
    model VARCHAR(200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, seq)
);
