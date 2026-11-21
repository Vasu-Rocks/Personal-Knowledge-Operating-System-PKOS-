"""
LLM provider layer: one interface for Ollama, OpenAI and Anthropic.

Used by answer generation (chat_stream), graph extraction and community summaries (chat_text/chat_json),
so a user who picks a cloud provider gets a working knowledge graph too, not just chat answers.
Failures raise LLMError with a message that is safe to show in the UI (no keys, no raw exception text).
"""
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import httpx

from core import config

logger = logging.getLogger(__name__)

PROVIDERS = ("ollama", "openai", "anthropic")
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# Tests replace this with httpx.MockTransport; None means real network.
_transport: httpx.AsyncBaseTransport | None = None


def make_client(timeout: float = 120.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, transport=_transport)


class LLMError(Exception):
    """A provider failure with a user-presentable message."""


@dataclass
class LLMSettings:
    provider: str = "ollama"
    ollama_model: str = ""
    openai_model: str = ""
    anthropic_model: str = ""
    openai_key: str | None = field(default=None, repr=False)
    anthropic_key: str | None = field(default=None, repr=False)

    @property
    def model(self) -> str:
        if self.provider == "openai":
            return self.openai_model or config.OPENAI_DEFAULT_MODEL
        if self.provider == "anthropic":
            return self.anthropic_model or config.ANTHROPIC_DEFAULT_MODEL
        return self.ollama_model or config.get_ollama_model()

    @property
    def label(self) -> str:
        return {"openai": "OpenAI", "anthropic": "Anthropic"}.get(self.provider, "Ollama")

    def api_key(self) -> str:
        key = self.openai_key if self.provider == "openai" else self.anthropic_key
        if not key:
            raise LLMError(f"{self.label} API key is missing. Add it in Settings.")
        return key

    @classmethod
    def from_dict(cls, d: dict | None) -> "LLMSettings":
        d = d or {}
        provider = d.get("provider") or "ollama"
        return cls(
            provider=provider if provider in PROVIDERS else "ollama",
            ollama_model=d.get("ollama_model") or "",
            openai_model=d.get("openai_model") or "",
            anthropic_model=d.get("anthropic_model") or "",
            openai_key=d.get("openai_key") or None,
            anthropic_key=d.get("anthropic_key") or None,
        )


# --------------------------------------------------------------------------- request building

def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    system = "\n".join(m["content"] for m in messages if m["role"] == "system").strip()
    return system, [m for m in messages if m["role"] != "system"]


def _with_json_instruction(messages: list[dict], schema: dict | None) -> list[dict]:
    """Cloud providers get the schema as an instruction (Ollama enforces it natively via `format`)."""
    note = "Reply with only a JSON object, no other text."
    if schema:
        note += " It must match this JSON Schema:\n" + json.dumps(schema)
    system, rest = _split_system(messages)
    return [{"role": "system", "content": f"{system}\n\n{note}".strip()}] + rest


def _openai_payload(s: LLMSettings, messages, *, stream, temperature, max_tokens, json_mode) -> dict:
    payload = {"model": s.model, "messages": messages, "stream": stream, "max_completion_tokens": max_tokens}
    # Reasoning models only accept the default temperature.
    if not s.model.startswith(("o1", "o3", "o4", "gpt-5")):
        payload["temperature"] = temperature
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    return payload


def _anthropic_payload(s: LLMSettings, messages, *, stream, temperature, max_tokens) -> dict:
    system, rest = _split_system(messages)
    payload = {"model": s.model, "messages": rest, "max_tokens": max_tokens, "temperature": temperature, "stream": stream}
    if system:
        payload["system"] = system
    return payload


def _ollama_payload(s: LLMSettings, messages, *, stream, temperature, max_tokens, num_ctx, fmt=None) -> dict:
    payload = {
        "model": s.model, "messages": messages, "stream": stream, "keep_alive": "15m",
        "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": num_ctx, "top_p": 0.9},
    }
    if fmt is not None:
        payload["format"] = fmt
    return payload


def _request(s: LLMSettings, payload: dict) -> tuple[str, dict]:
    if s.provider == "openai":
        return OPENAI_URL, {"Authorization": f"Bearer {s.api_key()}"}
    if s.provider == "anthropic":
        return ANTHROPIC_URL, {"x-api-key": s.api_key(), "anthropic-version": ANTHROPIC_VERSION}
    return config.OLLAMA_CHAT_URL, {}


# --------------------------------------------------------------------------- error mapping

def _http_error(s: LLMSettings, status: int, body: str) -> LLMError:
    logger.error(f"{s.label} returned {status}: {body[:500]}")
    if s.provider == "ollama" and status == 404:
        return LLMError(f"Model '{s.model}' is not installed in Ollama. Download it in Settings.")
    if status in (401, 403):
        return LLMError(f"{s.label} rejected the API key. Check it in Settings.")
    if status == 404:
        return LLMError(f"{s.label} does not know the model '{s.model}'. Pick another model in Settings.")
    if status == 429:
        return LLMError(f"{s.label} rate limit or quota reached. Try again later.")
    return LLMError(f"{s.label} returned status {status}.")


@asynccontextmanager
async def _errors(s: LLMSettings):
    try:
        yield
    except LLMError:
        raise
    except httpx.ConnectError:
        logger.exception(f"{s.label} connection failed")
        if s.provider == "ollama":
            raise LLMError(f"Cannot reach Ollama at {config.OLLAMA_BASE_URL}. Is it running?") from None
        raise LLMError(f"Cannot reach {s.label}. Check your internet connection.") from None
    except httpx.TimeoutException:
        logger.exception(f"{s.label} timed out")
        raise LLMError(f"{s.label} timed out. The model may still be loading; try again.") from None
    except Exception:
        logger.exception(f"{s.label} request failed")
        raise LLMError("Unexpected failure talking to the AI model. See the server log for details.") from None


@asynccontextmanager
async def _client_ctx(client: httpx.AsyncClient | None, timeout: float):
    if client is not None:
        yield client
    else:
        async with make_client(timeout) as c:
            yield c


# --------------------------------------------------------------------------- public API

async def chat_stream(s: LLMSettings, messages: list[dict], *, temperature: float = 0.1, max_tokens: int = 512,
                      num_ctx: int = 4096, client: httpx.AsyncClient | None = None):
    """Yields answer text pieces as they arrive. Raises LLMError."""
    if s.provider == "openai":
        payload = _openai_payload(s, messages, stream=True, temperature=temperature, max_tokens=max_tokens, json_mode=False)
    elif s.provider == "anthropic":
        payload = _anthropic_payload(s, messages, stream=True, temperature=temperature, max_tokens=max_tokens)
    else:
        payload = _ollama_payload(s, messages, stream=True, temperature=temperature, max_tokens=max_tokens, num_ctx=num_ctx)

    async with _errors(s):
        url, headers = _request(s, payload)
        async with _client_ctx(client, 120.0) as c, c.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                raise _http_error(s, resp.status_code, (await resp.aread()).decode("utf-8", errors="ignore"))
            event = None
            async for line in resp.aiter_lines():
                if not line:
                    continue
                if s.provider == "ollama":
                    data = json.loads(line)
                    if data.get("error"):
                        raise _http_error(s, 500, data["error"])
                    piece = data.get("message", {}).get("content", "")
                elif line.startswith("event: "):
                    event = line[7:].strip()
                    continue
                elif line.startswith("data: "):
                    raw = line[6:].strip()
                    if raw == "[DONE]":
                        break
                    data = json.loads(raw)
                    if s.provider == "openai":
                        choices = data.get("choices") or [{}]
                        piece = (choices[0].get("delta") or {}).get("content") or ""
                    else:
                        if event == "error" or data.get("type") == "error":
                            raise _http_error(s, 500, raw)
                        piece = data.get("delta", {}).get("text", "") if data.get("type") == "content_block_delta" else ""
                else:
                    continue
                if piece:
                    yield piece


async def chat_text(s: LLMSettings, messages: list[dict], *, json_mode: bool = False, schema: dict | None = None,
                    temperature: float = 0.0, max_tokens: int = 1024, num_ctx: int = 2048,
                    client: httpx.AsyncClient | None = None, timeout: float = 180.0) -> str:
    """One non-streaming completion; returns the raw text. Raises LLMError."""
    if s.provider != "ollama" and (json_mode or schema):
        messages = _with_json_instruction(messages, schema)
    if s.provider == "openai":
        payload = _openai_payload(s, messages, stream=False, temperature=temperature, max_tokens=max_tokens,
                                  json_mode=json_mode or bool(schema))
    elif s.provider == "anthropic":
        payload = _anthropic_payload(s, messages, stream=False, temperature=temperature, max_tokens=max_tokens)
    else:
        fmt = schema if schema else ("json" if json_mode else None)
        payload = _ollama_payload(s, messages, stream=False, temperature=temperature, max_tokens=max_tokens,
                                  num_ctx=num_ctx, fmt=fmt)

    async with _errors(s):
        url, headers = _request(s, payload)
        async with _client_ctx(client, timeout) as c:
            resp = await c.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            raise _http_error(s, resp.status_code, resp.text)
        data = resp.json()
        if s.provider == "openai":
            return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        if s.provider == "anthropic":
            return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        return data.get("message", {}).get("content", "")


def extract_json(text: str) -> dict | None:
    """Parses a JSON object from model output, tolerating code fences or text around it."""
    text = (text or "").strip()
    for candidate in (text, text[text.find("{"): text.rfind("}") + 1] if "{" in text else ""):
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            continue
    return None


async def chat_json(s: LLMSettings, messages: list[dict], *, schema: dict | None = None, **kw) -> dict | None:
    """Completion parsed as a JSON object; None if the model produced invalid JSON. Raises LLMError."""
    return extract_json(await chat_text(s, messages, json_mode=True, schema=schema, **kw))


async def test_connection(s: LLMSettings) -> str:
    """Tiny round trip to validate the provider, key and model. Returns the reply; raises LLMError."""
    reply = await chat_text(s, [{"role": "user", "content": "Reply with the single word: OK"}],
                            max_tokens=16, temperature=0.0, num_ctx=512, timeout=60.0)
    return reply.strip()[:50]
