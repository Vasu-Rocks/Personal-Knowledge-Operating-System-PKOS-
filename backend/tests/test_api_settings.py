"""Per-user AI settings: keys are write-only, encrypted at rest, isolated per user, and used by the query path."""
import asyncio
import json
import os

import httpx
import pytest

from core import llm

URL = "/api/v1/settings/llm"
KEY = "sk-test-SECRET-abcdef-9876"


def raw_row(username):
    import asyncpg

    async def fetch():
        conn = await asyncpg.connect(
            host=os.environ["POSTGRES_HOST"], port=int(os.environ["POSTGRES_PORT"]),
            user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
            database=os.environ["POSTGRES_DB"])
        try:
            return await conn.fetchrow("""
                SELECT s.* FROM user_llm_settings s JOIN users u ON u.user_id = s.user_id WHERE u.username = $1
            """, username)
        finally:
            await conn.close()

    return asyncio.run(fetch())


def test_defaults_before_saving(make_user):
    u = make_user("fresh")
    r = u.client.get(URL, headers=u.headers)
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "ollama" and body["saved"] is False
    assert body["openai_key_set"] is False and body["effective_model"]


def test_requires_auth(client):
    assert client.get(URL).status_code == 401
    assert client.put(URL, json={"provider": "ollama"}).status_code == 401


def test_key_is_write_only_and_encrypted_at_rest(make_user):
    u = make_user("keys")
    r = u.client.put(URL, json={"provider": "openai", "openai_model": "gpt-4o-mini", "openai_key": KEY}, headers=u.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert KEY not in r.text
    assert body["openai_key_set"] is True and body["openai_key_hint"] == "…9876"
    assert body["provider"] == "openai" and body["effective_model"] == "gpt-4o-mini"

    assert KEY not in u.client.get(URL, headers=u.headers).text
    row = raw_row(u.username)
    assert row["openai_key_enc"] and KEY not in row["openai_key_enc"]


def test_omitted_key_is_kept_and_empty_key_removes_it(make_user):
    u = make_user("keep")
    u.client.put(URL, json={"provider": "anthropic", "anthropic_key": KEY}, headers=u.headers)

    body = u.client.put(URL, json={"provider": "ollama", "ollama_model": "llama3.2:1b"}, headers=u.headers).json()
    assert body["anthropic_key_set"] is True and body["provider"] == "ollama"
    assert body["effective_model"] == "llama3.2:1b"

    body = u.client.put(URL, json={"provider": "ollama", "anthropic_key": ""}, headers=u.headers).json()
    assert body["anthropic_key_set"] is False and body["anthropic_key_hint"] is None
    assert raw_row(u.username)["anthropic_key_enc"] is None


def test_settings_are_isolated_between_users(make_user):
    alice, bob = make_user("alice"), make_user("bob")
    alice.client.put(URL, json={"provider": "openai", "openai_key": KEY}, headers=alice.headers)
    body = bob.client.get(URL, headers=bob.headers).json()
    assert body["saved"] is False and body["openai_key_set"] is False and body["provider"] == "ollama"


@pytest.mark.parametrize("payload", [
    {"provider": "evil"},
    {"provider": "ollama", "ollama_model": "bad model; rm -rf"},
    {"provider": "openai", "openai_key": "x" * 401},
])
def test_rejects_invalid_input(make_user, payload):
    u = make_user("invalid")
    assert u.client.put(URL, json=payload, headers=u.headers).status_code == 422


def test_connection_test_uses_unsaved_values(make_user, monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        if request.headers.get("authorization") == f"Bearer {KEY}":
            return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
        return httpx.Response(401, text="bad key")

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    u = make_user("tester")
    good = u.client.post(f"{URL}/test", json={"provider": "openai", "openai_key": KEY}, headers=u.headers).json()
    assert good == {"ok": True, "provider": "openai", "model": "gpt-4o-mini", "reply": "OK"}

    bad = u.client.post(f"{URL}/test", json={"provider": "openai", "openai_key": "sk-wrong-000000"}, headers=u.headers).json()
    assert bad["ok"] is False and "rejected the API key" in bad["detail"]
    assert u.client.get(URL, headers=u.headers).json()["saved"] is False  # testing never saves


def test_query_uses_saved_settings_over_headers(make_user, monkeypatch):
    from api import routes_query

    captured = []

    async def capture_stream(prompt, settings=None):
        captured.append(settings)
        yield json.dumps({"type": "token", "content": "ok"})

    monkeypatch.setattr(routes_query, "generate_rag_response_stream", capture_stream)
    u = make_user("querier")
    text = "Zephyr glaciers sensors research notes. " * 3  # the cleaner drops pages under 50 characters
    assert u.upload("notes.txt", text.encode()).status_code == 202
    question = text.strip()  # identical text -> distance 0 with the fake embedder

    legacy = {"X-LLM-Provider": "anthropic", "X-Anthropic-Key": "sk-ant-header-key-0000"}
    r = u.client.post("/api/v1/query/stream", json={"query": question}, headers={**u.headers, **legacy})
    assert captured, r.text
    assert captured[-1].provider == "anthropic"  # nothing saved yet: legacy headers apply

    u.client.put(URL, json={"provider": "openai", "openai_key": KEY}, headers=u.headers)
    u.client.post("/api/v1/query/stream", json={"query": question}, headers={**u.headers, **legacy})
    assert captured[-1].provider == "openai" and captured[-1].openai_key == KEY
