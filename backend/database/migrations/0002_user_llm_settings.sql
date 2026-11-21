-- Per-user AI provider settings (desktop app plan D1-4). API keys are stored encrypted (core/crypto.py);
-- the hint columns hold only the last 4 characters so the UI can show which key is saved.
CREATE TABLE IF NOT EXISTS user_llm_settings (
    user_id UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    provider VARCHAR(20) NOT NULL DEFAULT 'ollama' CHECK (provider IN ('ollama', 'openai', 'anthropic')),
    ollama_model VARCHAR(200),
    openai_model VARCHAR(200),
    anthropic_model VARCHAR(200),
    openai_key_enc TEXT,
    openai_key_hint VARCHAR(20),
    anthropic_key_enc TEXT,
    anthropic_key_hint VARCHAR(20),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
