import os

# Ollama endpoints and model, shared by the query path and the graph workers.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_GENERATE_URL = f"{OLLAMA_BASE_URL}/api/generate"


def get_ollama_model() -> str:
    # Read at call time so an env override applies without a restart.
    return os.getenv("OLLAMA_MODEL", "llama3.2")
