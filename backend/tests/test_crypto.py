from core import crypto


def test_round_trip_and_ciphertext_hides_the_key():
    token = crypto.encrypt("sk-live-abcdef123456")
    assert "sk-live" not in token
    assert crypto.decrypt(token) == "sk-live-abcdef123456"


def test_tokens_are_randomised():
    assert crypto.encrypt("same") != crypto.encrypt("same")


def test_wrong_secret_reads_as_not_set(monkeypatch):
    token = crypto.encrypt("sk-live-abcdef123456")
    monkeypatch.setenv("PKOS_SETTINGS_KEY", "a-different-secret-entirely")
    assert crypto.decrypt(token) is None


def test_empty_and_garbage():
    assert crypto.decrypt(None) is None
    assert crypto.decrypt("") is None
    assert crypto.decrypt("not-a-token") is None


def test_hint_shows_only_last_four():
    assert crypto.hint("sk-live-abcdef123456") == "…3456"
    assert crypto.hint("short") == "…"
