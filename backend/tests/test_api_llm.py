"""AI readiness, Ollama model management and system status, against a fake Ollama."""
import json

import httpx
import pytest

from core import llm

TAGS = {"models": [
    {"name": "llama3.2:latest", "size": 2_000_000_000, "modified_at": "2026-01-01", "details": {"parameter_size": "3.2B"}},
]}


class FakeOllama:
    def __init__(self, reachable=True):
        self.reachable = reachable
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        if not self.reachable:
            raise httpx.ConnectError("refused", request=request)
        path = request.url.path
        if path == "/api/tags":
            return httpx.Response(200, json=TAGS)
        if path == "/api/pull":
            name = json.loads(request.content)["model"]
            if name == "missing-model":
                return httpx.Response(200, text=json.dumps({"error": "pull model manifest: file does not exist"}) + "\n")
            lines = [{"status": "pulling manifest"},
                     {"status": "downloading", "total": 200, "completed": 50},
                     {"status": "downloading", "total": 200, "completed": 200},
                     {"status": "success"}]
            return httpx.Response(200, text="\n".join(json.dumps(x) for x in lines) + "\n")
        if path == "/api/delete":
            name = json.loads(request.content)["model"]
            return httpx.Response(200) if name == "llama3.2:latest" else httpx.Response(404, json={"error": "not found"})
        return httpx.Response(404)


@pytest.fixture
def ollama(monkeypatch):
    def install(**kw):
        fake = FakeOllama(**kw)
        monkeypatch.setattr(llm, "_transport", httpx.MockTransport(fake))
        return fake
    return install


def sse_events(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def test_status_ready_with_installed_default_model(make_user, ollama):
    ollama()
    u = make_user("ready")
    body = u.client.get("/api/v1/llm/status", headers=u.headers).json()
    assert body["ready"] is True and body["provider"] == "ollama" and body["configured"] is False
    assert body["ollama"] == {"reachable": True, "models": ["llama3.2:latest"]}  # 'llama3.2' matches ':latest'


def test_status_model_not_downloaded(make_user, ollama):
    ollama()
    u = make_user("nomodel")
    u.client.put("/api/v1/settings/llm", json={"provider": "ollama", "ollama_model": "qwen3:4b"}, headers=u.headers)
    body = u.client.get("/api/v1/llm/status", headers=u.headers).json()
    assert body["ready"] is False and "not downloaded" in body["message"] and body["configured"] is True


def test_status_ollama_down_and_cloud_key(make_user, ollama):
    ollama(reachable=False)
    u = make_user("cloud")
    body = u.client.get("/api/v1/llm/status", headers=u.headers).json()
    assert body["ready"] is False and body["ollama"]["reachable"] is False

    u.client.put("/api/v1/settings/llm", json={"provider": "anthropic"}, headers=u.headers)
    assert "API key is missing" in u.client.get("/api/v1/llm/status", headers=u.headers).json()["message"]
    u.client.put("/api/v1/settings/llm", json={"provider": "anthropic", "anthropic_key": "sk-ant-0123456789"},
                 headers=u.headers)
    assert u.client.get("/api/v1/llm/status", headers=u.headers).json()["ready"] is True


def test_list_models(make_user, ollama):
    ollama()
    u = make_user("lister")
    models = u.client.get("/api/v1/ollama/models", headers=u.headers).json()["models"]
    assert models == [{"name": "llama3.2:latest", "size": 2_000_000_000, "modified_at": "2026-01-01",
                       "parameter_size": "3.2B"}]


def test_list_models_when_ollama_down(make_user, ollama):
    ollama(reachable=False)
    u = make_user("down")
    assert u.client.get("/api/v1/ollama/models", headers=u.headers).status_code == 503


def test_pull_streams_progress(make_user, ollama):
    fake = ollama()
    u = make_user("puller")
    r = u.client.post("/api/v1/ollama/pull", json={"model": "llama3.2:1b"}, headers=u.headers)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = sse_events(r.text)
    assert events[0] == {"status": "pulling manifest"}
    assert events[1]["percent"] == 25.0 and events[2]["percent"] == 100.0
    assert events[-1] == {"status": "success"}
    assert json.loads(fake.requests[-1].content) == {"model": "llama3.2:1b", "stream": True}


def test_pull_reports_errors(make_user, ollama):
    ollama()
    u = make_user("pullerr")
    events = sse_events(u.client.post("/api/v1/ollama/pull", json={"model": "missing-model"}, headers=u.headers).text)
    assert events[-1]["status"] == "error" and "does not exist" in events[-1]["error"]

    ollama(reachable=False)
    events = sse_events(u.client.post("/api/v1/ollama/pull", json={"model": "llama3.2"}, headers=u.headers).text)
    assert events == [{"status": "error", "error": "Ollama is not running."}]


def test_pull_and_delete_validate_names(make_user, ollama):
    fake = ollama()
    u = make_user("names")
    assert u.client.post("/api/v1/ollama/pull", json={"model": "../../etc"}, headers=u.headers).status_code == 422
    assert u.client.delete("/api/v1/ollama/models/bad name", headers=u.headers).status_code == 422
    assert fake.requests == []


def test_delete_model(make_user, ollama):
    ollama()
    u = make_user("deleter")
    assert u.client.delete("/api/v1/ollama/models/llama3.2:latest", headers=u.headers).json() == {"deleted": "llama3.2:latest"}
    assert u.client.delete("/api/v1/ollama/models/other:7b", headers=u.headers).status_code == 404


def test_model_routes_require_auth(client):
    assert client.get("/api/v1/llm/status").status_code == 401
    assert client.get("/api/v1/ollama/models").status_code == 401
    assert client.post("/api/v1/ollama/pull", json={"model": "x"}).status_code == 401
    assert client.delete("/api/v1/ollama/models/x").status_code == 401
    assert client.get("/api/v1/system/status").status_code == 401


def test_system_status(make_user, ollama):
    ollama()
    u = make_user("status")
    body = u.client.get("/api/v1/system/status", headers=u.headers).json()
    assert body["database"] is True and body["ollama"] is True
    assert body["graph_worker_running"] is True
    assert body["graph_jobs"] == {"pending": 0, "processing": 0, "failed": 0}
    assert body["embedder_ready"] is False  # warm-up is disabled in tests
    assert isinstance(body["disk_free_bytes"], int)
