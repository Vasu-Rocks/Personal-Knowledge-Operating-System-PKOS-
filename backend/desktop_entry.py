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


def _tiny_pdf() -> bytes:
    """A valid one-page PDF with a line of text, built in memory (no file needed in the frozen app)."""
    stream = b"BT /F1 12 Tf 20 50 Td (PKOS smoke test) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objects) + 1, xref)


def smoke_test():
    """`pkos-api.exe --smoke-test`: import everything the app needs (catches missing modules/data in a frozen build)."""
    import io

    import main  # noqa: F401  (imports every route, the graph worker and the provider layer)
    from database.postgres_core import MIGRATIONS_DIR
    from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: F401
    import sentence_transformers  # noqa: F401
    from rag.ingestion.extractors import extract_pdf_stream

    migrations = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    if not migrations:
        raise SystemExit(f"no migrations in {MIGRATIONS_DIR}")
    # Reads a real PDF: proves the native PDFium library was bundled and loads (an import alone would not).
    pages = list(extract_pdf_stream(io.BytesIO(_tiny_pdf())))
    if not pages or "PKOS smoke test" not in pages[0][1]:
        raise SystemExit(f"PDF extraction does not work in this build: {pages!r}")
    print(f"smoke test ok: {len(migrations)} migrations, PDF extraction, sentence-transformers {sentence_transformers.__version__}")


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
