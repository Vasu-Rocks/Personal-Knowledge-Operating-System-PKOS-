import asyncio
import importlib
import os

import pytest


def test_prod_refuses_to_boot_without_secret(monkeypatch):
    from core import security

    monkeypatch.setenv("ENV", "prod")
    monkeypatch.delenv("PKOS_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="PKOS_SECRET_KEY"):
        security._get_secret_key()


def test_dev_without_secret_falls_back_to_random_key(monkeypatch):
    from core import security

    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("PKOS_SECRET_KEY", raising=False)
    a, b = security._get_secret_key(), security._get_secret_key()
    assert len(a) >= 32 and a != b


def test_prod_with_secret_is_fine(monkeypatch):
    from core import security

    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("PKOS_SECRET_KEY", "x" * 40)
    assert security._get_secret_key() == "x" * 40


def test_token_ttl_is_configurable(monkeypatch):
    monkeypatch.setenv("TOKEN_TTL_MINUTES", "5")
    from core import security

    try:
        importlib.reload(security)
        assert security.ACCESS_TOKEN_EXPIRE_MINUTES == 5
    finally:
        monkeypatch.delenv("TOKEN_TTL_MINUTES")
        importlib.reload(security)


def test_migrations_are_recorded_and_idempotent(client):
    import asyncpg

    async def check():
        conn = await asyncpg.connect(
            host=os.environ["POSTGRES_HOST"], port=int(os.environ["POSTGRES_PORT"]),
            user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
            database=os.environ["POSTGRES_DB"])
        try:
            from database.postgres_core import apply_migrations

            await apply_migrations(conn)  # second run must be a no-op
            versions = [r["version"] for r in await conn.fetch("SELECT version FROM schema_version ORDER BY version")]
            cols = [r["column_name"] for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'chunk_entity_junction'")]
            return versions, cols
        finally:
            await conn.close()

    versions, cols = asyncio.run(check())
    assert versions == [1, 2, 3, 4]
    assert "mention_snippet" not in cols


def test_desktop_mode_refuses_to_boot_without_secret(monkeypatch):
    from core import security

    monkeypatch.setenv("ENV", "desktop")
    monkeypatch.delenv("PKOS_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ENV=desktop"):
        security._get_secret_key()


def test_importing_the_app_does_not_load_torch():
    """API startup must not wait for torch (~14 s); the embedder loads it lazily / in the background."""
    import subprocess
    import sys

    code = "import main, sys; print('torch' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                         cwd=os.path.dirname(os.path.dirname(__file__)), env={**os.environ})
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1] == "False"
