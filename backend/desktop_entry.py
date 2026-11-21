"""
Entry point for the desktop app: started by Electron (dev: with the venv's Python; packaged: as the PyInstaller
build pkos-api.exe). Electron passes everything through environment variables (ENV=desktop, PKOS_API_PORT, ...).
"""
import multiprocessing
import os
import threading


def exit_with_parent(parent_pid: int):
    """If the Electron app dies without stopping us (killed from Task Manager, crash), exit too instead of lingering."""
    if os.name != "nt":
        return
    import ctypes

    synchronize, infinite = 0x00100000, 0xFFFFFFFF
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(synchronize, False, parent_pid)
    if not handle:
        return

    def watch():
        kernel32.WaitForSingleObject(handle, infinite)
        os._exit(0)  # graph jobs are checkpointed in Postgres and resume on the next start

    threading.Thread(target=watch, name="parent-watchdog", daemon=True).start()


def smoke_test():
    """`pkos-api.exe --smoke-test`: import everything the app needs (catches missing modules/data in a frozen build)."""
    import main  # noqa: F401  (imports every route, the graph worker and the provider layer)
    from database.postgres_core import MIGRATIONS_DIR
    from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: F401
    import fitz  # noqa: F401
    import sentence_transformers  # noqa: F401

    migrations = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    if not migrations:
        raise SystemExit(f"no migrations in {MIGRATIONS_DIR}")
    print(f"smoke test ok: {len(migrations)} migrations, sentence-transformers {sentence_transformers.__version__}")


if __name__ == "__main__":
    import sys

    multiprocessing.freeze_support()
    if "--smoke-test" in sys.argv:
        smoke_test()
        raise SystemExit(0)
    if os.getenv("PKOS_PARENT_PID"):
        exit_with_parent(int(os.environ["PKOS_PARENT_PID"]))

    import uvicorn

    from main import app

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PKOS_API_PORT", "8000")), log_level="info",
                access_log=False)
