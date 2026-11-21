import logging
import threading

import numpy as np

from core import config

logger = logging.getLogger(__name__)

# Sub-Module 2.2: CPU-bound vector embedding (BAAI/bge-small-en-v1.5, 384-d).
# sentence_transformers (and torch) are imported on first use, not at import time: importing torch takes
# ~14 s, and the API should answer /health while the model loads in the background (see warm_up()).
_embedder_model = None
_lock = threading.Lock()


def get_embedder():
    global _embedder_model
    if _embedder_model is None:
        with _lock:
            if _embedder_model is None:
                from sentence_transformers import SentenceTransformer

                logger.info(f"Loading embedding model {config.EMBED_MODEL}...")
                _embedder_model = SentenceTransformer(
                    config.EMBED_MODEL, device="cpu", cache_folder=config.EMBED_CACHE_DIR)
                logger.info("Embedding model ready.")
    return _embedder_model


def is_ready() -> bool:
    return _embedder_model is not None


def warm_up():
    """Loads the model; called in a thread right after startup. Failures are logged, the first real call retries."""
    try:
        get_embedder()
    except Exception:
        logger.exception("Embedding model warm-up failed")


def embed_text_batch(texts: list[str]) -> np.ndarray:
    """Returns normalised float32 vectors, shape (len(texts), 384)."""
    model = get_embedder()
    vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return vectors.astype('float32')


def embed_query(query: str) -> np.ndarray:
    """
    Sub-Module 3.1: Query Vectorization, with the BGE query instruction prefix.
    Returns shape (1, 384).
    """
    query = query.strip()
    if not query:
        raise ValueError("Query cannot be empty.")

    instruction = "Represent this sentence for searching relevant passages: "
    model = get_embedder()
    vector = model.encode([instruction + query], normalize_embeddings=True, convert_to_numpy=True)
    return vector.astype('float32')
