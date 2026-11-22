import logging
import logging.handlers
import os
from pathlib import Path

# Ollama endpoint, shared by the query path, the graph workers and model management.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_GENERATE_URL = f"{OLLAMA_BASE_URL}/api/generate"
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/api/chat"


def get_ollama_model() -> str:
    # Read at call time so an env override applies without a restart.
    return os.getenv("OLLAMA_MODEL", "llama3.2")


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# Runtime mode: "dev" (default), "prod" (Docker/server) or "desktop" (the packaged app). prod and desktop
# refuse to start without PKOS_SECRET_KEY.
ENV = os.getenv("ENV", "dev").strip().lower()
IS_HARDENED = ENV in ("prod", "desktop")

# Desktop app data folder (logs, model cache). Unset in dev/Docker: logs go to stdout only.
DATA_DIR = Path(os.environ["PKOS_DATA_DIR"]) if os.getenv("PKOS_DATA_DIR") else None

# Embedding model: a local folder (bundled with the desktop app, works offline) or a Hugging Face model id.
EMBED_MODEL = os.getenv("PKOS_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_CACHE_DIR = os.getenv("PKOS_EMBED_CACHE_DIR") or (str(DATA_DIR / "models") if DATA_DIR else None)
# Load the embedding model in the background right after startup, so the first upload/query is not slow.
EMBED_WARMUP = _env_bool("PKOS_EMBED_WARMUP", True)

# Default cloud models (each user can override them in their LLM settings).
OPENAI_DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")

# Graph-augmented local search (G4). GRAPH_LOCAL_EXPANSION=false restores the pre-G4 behaviour.
GRAPH_LOCAL_EXPANSION = _env_bool("GRAPH_LOCAL_EXPANSION", True)
GRAPH_SEEDS = int(os.getenv("GRAPH_SEEDS", "5"))
GRAPH_MAX_EDGES = int(os.getenv("GRAPH_MAX_EDGES", "20"))
GRAPH_EXTRA_CHUNKS = int(os.getenv("GRAPH_EXTRA_CHUNKS", "2"))
GRAPH_SEED_MAX_DISTANCE = float(os.getenv("GRAPH_SEED_MAX_DISTANCE", "0.35"))
GRAPH_CHUNK_MAX_DISTANCE = float(os.getenv("GRAPH_CHUNK_MAX_DISTANCE", "0.45"))
# Prompt budget (characters, ~4 chars/token; the model runs with num_ctx 4096).
CONTEXT_MAX_CHARS = int(os.getenv("CONTEXT_MAX_CHARS", "6000"))
GRAPH_CONTEXT_MAX_CHARS = int(os.getenv("GRAPH_CONTEXT_MAX_CHARS", "1800"))

# Conversation memory (docs/07_MEMORY_PLAN.md). Budget with num_ctx 4096: rules ~1200 + documents 6000 + graph 1800
# + history 2400 + summary 1200 characters ~ 3150 tokens, leaving room for a 512-token answer.
MEMORY_ENABLED = _env_bool("MEMORY_ENABLED", True)
HISTORY_MAX_TURNS = int(os.getenv("HISTORY_MAX_TURNS", "6"))
HISTORY_MAX_CHARS = int(os.getenv("HISTORY_MAX_CHARS", "2400"))
SUMMARY_MAX_CHARS = int(os.getenv("SUMMARY_MAX_CHARS", "1200"))
# Follow-ups are rewritten into standalone questions before search; after this many seconds the question as typed is used.
# Generous on purpose: a local model that has to load first takes ~8 s, and that load is needed for the answer anyway.
REWRITE_TIMEOUT = float(os.getenv("REWRITE_TIMEOUT", "20"))

# Global search (G5): broad questions are answered from community summaries.
GRAPH_GLOBAL_SEARCH = _env_bool("GRAPH_GLOBAL_SEARCH", True)
GRAPH_COMMUNITIES = int(os.getenv("GRAPH_COMMUNITIES", "3"))
COMMUNITY_MAX_DISTANCE = float(os.getenv("COMMUNITY_MAX_DISTANCE", "0.5"))
COMMUNITY_MIN_MEMBERS = int(os.getenv("COMMUNITY_MIN_MEMBERS", "10"))
# Best community match worse than this => fall back to the largest communities (the corpus's main themes).
COMMUNITY_STRONG_DISTANCE = float(os.getenv("COMMUNITY_STRONG_DISTANCE", "0.36"))


def configure_logging():
    """stdout always; plus a rotating logs/api.log when running as the desktop app (PKOS_DATA_DIR set)."""
    fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt)
    if DATA_DIR:
        log_dir = DATA_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_dir / "api.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter(fmt))
        logging.getLogger().addHandler(handler)
