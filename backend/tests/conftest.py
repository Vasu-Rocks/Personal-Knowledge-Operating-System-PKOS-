import asyncio
import hashlib
import json
import os
import uuid

import numpy as np
import pytest

# Must be set before any module reads them at import time. The API tests run against a throwaway
# pgvector database (default: the Docker container from the README on port 5434), never the dev DB.
os.environ.setdefault("PKOS_SECRET_KEY", "test-secret-key-for-pytest-0123456789abcdef")
os.environ["PKOS_EMBED_WARMUP"] = "false"  # embeddings are faked; never load the real model in tests
os.environ["POSTGRES_HOST"] = os.getenv("TEST_POSTGRES_HOST", "localhost")
os.environ["POSTGRES_PORT"] = os.getenv("TEST_POSTGRES_PORT", "5434")
os.environ["POSTGRES_DB"] = os.getenv("TEST_POSTGRES_DB", "pkos_test")
os.environ["POSTGRES_USER"] = os.getenv("TEST_POSTGRES_USER", "postgres")
os.environ["POSTGRES_PASSWORD"] = os.getenv("TEST_POSTGRES_PASSWORD", "postgres")

DIM = 384


def fake_vector(text: str) -> np.ndarray:
    """Deterministic bag-of-words embedding: identical text gives distance 0, unrelated text gives ~1."""
    v = np.zeros(DIM, dtype="float32")
    for word in text.lower().split():
        v[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
    n = np.linalg.norm(v)
    return v / n if n else v


def sse_events(text: str) -> list:
    """The events of a /query/stream response: parsed JSON objects, and the final '[DONE]' as a string."""
    out = []
    for block in text.split("\n\n"):
        if block.startswith("data: "):
            data = block[len("data: "):]
            out.append(data if data == "[DONE]" else json.loads(data))
    return out


def run_db(fn):
    """Runs `fn(pool)` on a private pool (the app's pool belongs to the TestClient's event loop)."""
    from database.postgres_core import init_db_pool

    async def go():
        pool = await init_db_pool()
        try:
            return await fn(pool)
        finally:
            await pool.close()

    return asyncio.run(go())


def event(events: list, kind: str) -> dict:
    return next(e for e in events if isinstance(e, dict) and e.get("type") == kind)


def _db_reachable() -> bool:
    import asyncpg

    async def probe():
        conn = await asyncpg.connect(
            host=os.environ["POSTGRES_HOST"], port=int(os.environ["POSTGRES_PORT"]),
            user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
            database=os.environ["POSTGRES_DB"], timeout=3)
        await conn.close()

    try:
        asyncio.run(probe())
        return True
    except Exception:
        return False


def _reset_schema():
    import asyncpg

    async def reset():
        conn = await asyncpg.connect(
            host=os.environ["POSTGRES_HOST"], port=int(os.environ["POSTGRES_PORT"]),
            user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
            database=os.environ["POSTGRES_DB"])
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await conn.close()

    asyncio.run(reset())


@pytest.fixture(scope="session")
def client():
    """FastAPI app with a real lifespan (pool, schema, graph worker) on the test database; embeddings and LLM are faked."""
    if not _db_reachable():
        pytest.skip("Test database not reachable (start the pgvector container, see README 'Tests').")
    _reset_schema()

    from fastapi.testclient import TestClient
    import main
    from api import routes_ingest, routes_query

    async def fake_stream(prompt, settings=None):
        yield json.dumps({"type": "token", "content": "fake answer"})

    mp = pytest.MonkeyPatch()
    mp.setattr(routes_ingest, "embed_text_batch", lambda texts: np.stack([fake_vector(t) for t in texts]))
    mp.setattr(routes_query, "embed_query", lambda q: fake_vector(q).reshape(1, -1))
    mp.setattr(routes_query, "generate_rag_response_stream", fake_stream)
    with TestClient(main.app) as c:
        yield c
    mp.undo()


class User:
    def __init__(self, client, name):
        self.client = client
        self.username = f"{name}_{uuid.uuid4().hex[:8]}"
        self.email = f"{self.username}@example.com"
        self.password = "correct-horse-battery"
        r = client.post("/api/v1/register", json={
            "email": self.email, "username": self.username, "name": name.title(), "password": self.password})
        assert r.status_code == 200, r.text
        self.token = r.json()["access_token"]

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def upload(self, filename, content, build_graph=False):
        return self.client.post(
            "/api/v1/upload", params={"build_graph": str(build_graph).lower()},
            files={"file": (filename, content)}, headers=self.headers)

    def documents(self):
        r = self.client.get("/api/v1/documents", headers=self.headers)
        assert r.status_code == 200, r.text
        return r.json()["documents"]


@pytest.fixture
def make_user(client):
    return lambda name="user": User(client, name)
