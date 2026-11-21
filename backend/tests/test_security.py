from datetime import timedelta

import jwt
import pytest

from core import security


def test_password_roundtrip():
    h = security.get_password_hash("correct horse")
    assert security.verify_password("correct horse", h)
    assert not security.verify_password("wrong", h)


def test_overlong_password_rejected():
    with pytest.raises(ValueError):
        security.get_password_hash("a" * 72)
    assert not security.verify_password("a" * 72, security.get_password_hash("a"))


def test_token_contains_subject_and_expiry():
    token = security.create_access_token({"sub": "user-1"})
    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    assert payload["sub"] == "user-1" and "exp" in payload


def test_expired_token_is_rejected():
    token = security.create_access_token({"sub": "u"}, timedelta(seconds=-1))
    with pytest.raises(jwt.ExpiredSignatureError):
        jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])


def test_secret_comes_from_env():
    assert security.SECRET_KEY == "test-secret-key-for-pytest-0123456789abcdef"
