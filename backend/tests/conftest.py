import os

# Must be set before any module reads it at import time.
os.environ.setdefault("PKOS_SECRET_KEY", "test-secret-key-for-pytest-0123456789abcdef")
