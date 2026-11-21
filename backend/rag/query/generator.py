import json
import logging

import requests

from core import config
from core.llm import LLMError, LLMSettings, chat_stream

logger = logging.getLogger(__name__)

session = requests.Session()


def generate_rag_response(messages: list[dict[str, str]], model_name: str = None) -> str:
    """
    Blocking, Ollama-only generation. Used by the offline evaluation script (eval_graph.py); the app uses
    generate_rag_response_stream.
    """
    if not messages:
        logger.error("Generator received an empty messages array.")
        return "System Error: The system aborted generation because no context was successfully built."

    payload = {
        "model": model_name or config.get_ollama_model(),
        "messages": messages,
        "stream": False,
        "keep_alive": "15m",
        "options": {"temperature": 0.1, "num_predict": 512, "num_ctx": 4096, "top_p": 0.9},
    }
    try:
        response = session.post(config.OLLAMA_CHAT_URL, json=payload, timeout=120.0)
        if response.status_code != 200:
            logger.error(f"Ollama status {response.status_code}: {response.text}")
            return f"System Error: LLM Engine returned status {response.status_code}."
        return response.json().get("message", {}).get("content", "").strip()
    except requests.exceptions.ConnectionError:
        logger.exception("Ollama connection failed")
        return f"System Error: Cannot connect to {config.OLLAMA_BASE_URL}. Is Ollama running?"
    except requests.exceptions.Timeout:
        logger.exception("Ollama timed out")
        return "System Error: Inference timeout. Model took too long to load into RAM."
    except Exception:
        logger.exception("Unexpected generation failure")
        return "System Error: Unexpected failure. See the server log for details."


async def generate_rag_response_stream(messages: list[dict[str, str]], model_name: str = None,
                                       settings: LLMSettings | dict | None = None):
    """
    Sub-Module 3.4 (Streaming): yields SSE-ready JSON token events from the user's chosen provider.
    Provider errors become a single readable "System Error: ..." token instead of breaking the stream.
    """
    if not messages:
        logger.error("Generator received an empty messages array.")
        yield json.dumps({"type": "token", "content": "System Error: No context was successfully built."})
        return

    s = settings if isinstance(settings, LLMSettings) else LLMSettings.from_dict(settings)
    if model_name and s.provider == "ollama":
        s.ollama_model = model_name
    formatted = messages if isinstance(messages, list) else [{"role": "user", "content": str(messages)}]

    try:
        async for piece in chat_stream(s, formatted, temperature=0.1, max_tokens=1024 if s.provider != "ollama" else 512):
            yield json.dumps({"type": "token", "content": piece})
    except LLMError as e:
        yield json.dumps({"type": "token", "content": f"System Error: {e}"})
