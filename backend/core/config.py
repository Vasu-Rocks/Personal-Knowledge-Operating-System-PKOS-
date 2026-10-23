import os

# Ollama endpoints and model, shared by the query path and the graph workers.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_GENERATE_URL = f"{OLLAMA_BASE_URL}/api/generate"
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/api/chat"


def get_ollama_model() -> str:
    # Read at call time so an env override applies without a restart.
    return os.getenv("OLLAMA_MODEL", "llama3.2")


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


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
