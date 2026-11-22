# PyInstaller spec for the PKOS backend (desktop app). Build with packaging/build.ps1, which runs:
#   python -m PyInstaller packaging/pkos-api.spec --distpath build/pyinstaller/dist --workpath build/pyinstaller/work
# Output: a onedir folder pkos-api/ (onefile would unpack ~700 MB to %TEMP% on every start and trips antivirus more).
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent  # noqa: F821  (SPECPATH is provided by PyInstaller)
BACKEND = ROOT / "backend"

datas = [(str(BACKEND / "database" / "migrations"), "database/migrations")]
datas += collect_data_files("sentence_transformers")
datas += collect_data_files("transformers", includes=["**/*.json"])
# PDF engine: the PDFium shared library ships inside pypdfium2_raw (a missing library only shows up when a PDF is read;
# `pkos-api.exe --smoke-test` reads one during the build).
datas += collect_data_files("pypdfium2") + collect_data_files("pypdfium2_raw")
binaries = collect_dynamic_libs("pypdfium2_raw")
# Audio/image notes: faster-whisper (CTranslate2 + PyAV, plus its bundled voice-activity model) and RapidOCR on onnxruntime
# (its OCR models are data files). The Whisper model itself is staged separately by build.ps1.
for pkg in ("faster_whisper", "onnxruntime", "ctranslate2"):
    datas += collect_data_files(pkg)
# RapidOCR imports its detector/recognizer by name at run time (importlib, top-level names such as `ch_ppocr_v3_det`), so
# PyInstaller cannot see them: ship the .py files next to the models and list their imports as hidden imports below.
datas += collect_data_files("rapidocr_onnxruntime", include_py_files=True)
for pkg in ("ctranslate2", "onnxruntime", "av"):
    binaries += collect_dynamic_libs(pkg)
# Libraries that check their own or their dependencies' versions through importlib.metadata at import time.
for dist in ["transformers", "tokenizers", "huggingface-hub", "safetensors", "tqdm", "regex", "requests", "packaging",
             "filelock", "numpy", "pyyaml", "torch", "sentence-transformers", "scikit-learn", "scipy", "pypdfium2",
             "faster-whisper", "ctranslate2", "onnxruntime", "rapidocr-onnxruntime", "av"]:
    try:
        datas += copy_metadata(dist)
    except Exception:  # not installed: nothing to copy
        pass

hiddenimports = collect_submodules("uvicorn") + ["asyncpg.pgproto.pgproto"]
hiddenimports += collect_submodules("rapidocr_onnxruntime") + ["pyclipper", "shapely", "shapely.geometry", "cv2", "yaml", "six"]

# Not used by the backend; large. (faiss was pulled in by an old dependency; GUI/plotting/test stacks never run.)
excludes = [
    "fitz", "pymupdf",  # the AGPL PDF library PKOS no longer uses; keep it out even if it is still installed in the venv
    "faiss", "tkinter", "matplotlib", "IPython", "jupyter", "notebook", "pytest", "torch.utils.tensorboard",
    "tensorboard", "torchvision", "torchaudio", "triton",
]

a = Analysis(  # noqa: F821
    [str(BACKEND / "desktop_entry.py")],
    pathex=[str(BACKEND)],
    binaries=binaries,
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
