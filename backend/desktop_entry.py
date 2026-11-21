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


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if os.getenv("PKOS_PARENT_PID"):
        exit_with_parent(int(os.environ["PKOS_PARENT_PID"]))

    import uvicorn

    from main import app

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PKOS_API_PORT", "8000")), log_level="info",
                access_log=False)
