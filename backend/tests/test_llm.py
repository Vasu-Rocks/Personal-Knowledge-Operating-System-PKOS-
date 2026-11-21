"""Provider layer (core/llm.py) against a fake HTTP transport: request shapes, stream parsing, error messages."""
import asyncio
import json

import httpx
import pytest

from core import config, llm
from core.llm import LLMError, LLMSettings


class FakeServer:
    """Records requests and answers with a handler(request) -> httpx.Response."""

    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    @property
    def last_json(self):
        return json.loads(self.requests[-1].content)


@pytest.fixture
def server(monkeypatch):
    def install(handler):
        fake = FakeServer(handler)
        monkeypatch.setattr(llm, "_transport", httpx.MockTransport(fake))
        return fake
    return install


def run(coro):
    return asyncio.run(coro)


async def collect(agen):
    return [x async for x in agen]


MESSAGES = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Hi"}]
OPENAI = LLMSettings(provider="openai", openai_key="sk-test-1234567890")
ANTHROPIC = LLMSettings(provider="anthropic", anthropic_key="sk-ant-test-1234567890")


# --------------------------------------------------------------------------- streaming

def test_ollama_stream(server):
    body = "\n".join(json.dumps({"message": {"content": c}}) for c in ["Hel", "lo"]) + "\n"
    fake = server(lambda r: httpx.Response(200, text=body))
    pieces = run(collect(llm.chat_stream(LLMSettings(ollama_model="llama3.2"), MESSAGES)))
    assert pieces == ["Hel", "lo"]
    assert str(fake.requests[0].url) == config.OLLAMA_CHAT_URL
    sent = fake.last_json
    assert sent["model"] == "llama3.2" and sent["stream"] is True and sent["options"]["num_ctx"] == 4096
    assert sent["messages"] == MESSAGES  # Ollama takes the system message inline


def test_openai_stream(server):
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}" for c in ["A", "B"]] + ["data: [DONE]"]
    fake = server(lambda r: httpx.Response(200, text="\n\n".join(lines)))
    assert run(collect(llm.chat_stream(OPENAI, MESSAGES))) == ["A", "B"]
    req = fake.requests[0]
    assert str(req.url) == llm.OPENAI_URL
    assert req.headers["authorization"] == "Bearer sk-test-1234567890"
    sent = fake.last_json
    assert sent["model"] == config.OPENAI_DEFAULT_MODEL and "max_completion_tokens" in sent


def test_openai_reasoning_model_gets_no_temperature(server):
    fake = server(lambda r: httpx.Response(200, text="data: [DONE]"))
    run(collect(llm.chat_stream(LLMSettings(provider="openai", openai_key="k" * 12, openai_model="o4-mini"), MESSAGES)))
    assert "temperature" not in fake.last_json


def test_anthropic_stream_moves_system_prompt(server):
    events = [
        ("message_start", {"type": "message_start"}),
        ("content_block_delta", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Yo"}}),
        ("content_block_delta", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "!"}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    body = "\n\n".join(f"event: {e}\ndata: {json.dumps(d)}" for e, d in events)
    fake = server(lambda r: httpx.Response(200, text=body))
    assert run(collect(llm.chat_stream(ANTHROPIC, MESSAGES))) == ["Yo", "!"]
    req = fake.requests[0]
    assert req.headers["x-api-key"] == "sk-ant-test-1234567890"
    assert req.headers["anthropic-version"] == llm.ANTHROPIC_VERSION
    sent = fake.last_json
    assert sent["system"] == "Be brief."
    assert sent["messages"] == [{"role": "user", "content": "Hi"}]
    assert sent["model"] == config.ANTHROPIC_DEFAULT_MODEL and sent["max_tokens"] > 0


# --------------------------------------------------------------------------- JSON completions

SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}


def test_ollama_json_uses_native_format(server):
    fake = server(lambda r: httpx.Response(200, json={"message": {"content": '{"title": "x"}'}}))
    assert run(llm.chat_json(LLMSettings(), MESSAGES, schema=SCHEMA)) == {"title": "x"}
    sent = fake.last_json
    assert sent["format"] == SCHEMA and sent["stream"] is False
    assert sent["messages"] == MESSAGES


def test_openai_json_mode_and_schema_instruction(server):
    fake = server(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": '{"title": "y"}'}}]}))
    assert run(llm.chat_json(OPENAI, MESSAGES, schema=SCHEMA)) == {"title": "y"}
    sent = fake.last_json
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["messages"][0]["role"] == "system" and '"required": ["title"]' in sent["messages"][0]["content"]


def test_anthropic_json_tolerates_code_fences(server):
    text = 'Here you go:\n```json\n{"title": "z"}\n```'
    server(lambda r: httpx.Response(200, json={"content": [{"type": "text", "text": text}]}))
    assert run(llm.chat_json(ANTHROPIC, MESSAGES, schema=SCHEMA)) == {"title": "z"}


def test_invalid_json_returns_none(server):
    server(lambda r: httpx.Response(200, json={"message": {"content": "not json at all"}}))
    assert run(llm.chat_json(LLMSettings(), MESSAGES)) is None


@pytest.mark.parametrize("text,expected", [
    ('{"a": 1}', {"a": 1}),
    ('  ```json\n{"a": 1}\n```  ', {"a": 1}),
    ('prefix {"a": {"b": 2}} suffix', {"a": {"b": 2}}),
    ("[1, 2]", None),
    ("", None),
])
def test_extract_json(text, expected):
    assert llm.extract_json(text) == expected


# --------------------------------------------------------------------------- errors

def test_missing_key_fails_without_a_request(server):
    fake = server(lambda r: httpx.Response(200))
    with pytest.raises(LLMError, match="OpenAI API key is missing"):
        run(llm.chat_text(LLMSettings(provider="openai"), MESSAGES))
    assert fake.requests == []


@pytest.mark.parametrize("settings,status,message", [
    (OPENAI, 401, "rejected the API key"),
    (ANTHROPIC, 429, "rate limit"),
    (LLMSettings(ollama_model="nope"), 404, "'nope' is not installed"),
    (OPENAI, 404, "does not know the model"),
    (ANTHROPIC, 500, "returned status 500"),
])
def test_http_errors_become_readable(server, settings, status, message):
    server(lambda r: httpx.Response(status, text='{"error": "secret details sk-test-1234567890"}'))
    with pytest.raises(LLMError, match=message) as exc:
        run(llm.chat_text(settings, MESSAGES))
    assert "sk-test" not in str(exc.value)


def test_unreachable_ollama(server):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)
    server(refuse)
    with pytest.raises(LLMError, match="Cannot reach Ollama"):
        run(collect(llm.chat_stream(LLMSettings(), MESSAGES)))


def test_settings_from_dict_ignores_unknown_provider():
    s = LLMSettings.from_dict({"provider": "evil", "openai_key": ""})
    assert s.provider == "ollama" and s.openai_key is None


def test_settings_repr_hides_keys():
    assert "sk-test" not in repr(OPENAI)


# --------------------------------------------------------------------------- callers

def test_generator_turns_provider_errors_into_a_token(server):
    from rag.query.generator import generate_rag_response_stream

    server(lambda r: httpx.Response(401, text="nope"))
    events = run(collect(generate_rag_response_stream(MESSAGES, settings={"provider": "openai", "openai_key": "k" * 12})))
    assert len(events) == 1
    assert json.loads(events[0])["content"].startswith("System Error: OpenAI rejected the API key")


def test_extractor_works_with_a_cloud_provider(server):
    from rag.graph.extractor import extract_chunk

    reply = {"entities": [{"name": "FastAPI", "category": "TECHNOLOGY", "description": "A framework."},
                          {"name": "Invented", "category": "CONCEPT", "description": "Not in the text."}],
             "relationships": []}
    fake = server(lambda r: httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(reply)}]}))

    async def go():
        async with llm.make_client() as client:
            return await extract_chunk(client, "FastAPI is a Python framework.", "doc.txt", settings=ANTHROPIC)

    data = run(go())
    assert [e["name"] for e in data["entities"]] == ["FastAPI"]  # grounding still drops invented entities
    assert str(fake.requests[0].url) == llm.ANTHROPIC_URL
