# PyInstaller spec for the PKOS backend (desktop app). Build with packaging/build.ps1, which runs:
#   python -m PyInstaller packaging/pkos-api.spec --distpath build/pyinstaller/dist --workpath build/pyinstaller/work
# Output: a onedir folder pkos-api/ (onefile would unpack ~700 MB to %TEMP% on every start and trips antivirus more).
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent  # noqa: F821  (SPECPATH is provided by PyInstaller)
BACKEND = ROOT / "backend"

datas = [(str(BACKEND / "database" / "migrations"), "database/migrations")]
datas += collect_data_files("sentence_transformers")
datas += collect_data_files("transformers", includes=["**/*.json"])
# Libraries that check their own or their dependencies' versions through importlib.metadata at import time.
for dist in ["transformers", "tokenizers", "huggingface-hub", "safetensors", "tqdm", "regex", "requests", "packaging",
             "filelock", "numpy", "pyyaml", "torch", "sentence-transformers", "scikit-learn", "scipy"]:
    try:
        datas += copy_metadata(dist)
    except Exception:  # not installed: nothing to copy
        pass

hiddenimports = collect_submodules("uvicorn") + ["asyncpg.pgproto.pgproto"]

# Not used by the backend; large. (faiss was pulled in by an old dependency; GUI/plotting/test stacks never run.)
excludes = [
    "faiss", "tkinter", "matplotlib", "IPython", "jupyter", "notebook", "pytest", "torch.utils.tensorboard",
    "tensorboard", "torchvision", "torchaudio", "triton",
]

a = Analysis(  # noqa: F821
    [str(BACKEND / "desktop_entry.py")],
    pathex=[str(BACKEND)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="pkos-api",
    console=True,  # Electron hides the window (windowsHide); a console keeps stdout/stderr for the logs
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="pkos-api", upx=False)  # noqa: F821
