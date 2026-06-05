from sentence_transformers import SentenceTransformer
import numpy as np

# Sub-Module 2.2: CPU-Bound Vector Embedding
# Highly optimized for 0 GPU access. Singleton guarantees 1 single RAM payload across API calls.
_embedder_model = None

def get_embedder() -> SentenceTransformer:
    global _embedder_model
    if _embedder_model is None:
        _embedder_model = SentenceTransformer("BAAI/bge-small-en-v1.5", device='cpu')
    return _embedder_model

def embed_text_batch(texts: list[str]) -> np.ndarray:
    """
    Feeds exactly 32 strings at a time to the SentenceTransformer.
    Returns structurally guaranteed `float32` mappings (batch_size, 384).
    """
    # math format enforced specifically to interface flawlessly with FAISS
    model = get_embedder()
    vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return vectors.astype('float32')

def embed_query(query: str) -> np.ndarray:
    """
    Sub-Module 3.1: Query Vectorization
    Translates natural language questions into identical latent space maps.
    Enforces asymmetric instruction wrapping for BGE architectures.
    """
    query = query.strip()
    if not query:
        raise ValueError("Query cannot be empty.")
        
    instruction = "Represent this sentence for searching relevant passages: "
    formatted_query = instruction + query
    
    # We wrap inside a list to forcefully mandate a 2-Dimensional output array -> (1, 384)
    # This prevents FAISS index.search() from fatally crashing.
    model = get_embedder()
    vector = model.encode([formatted_query], normalize_embeddings=True, convert_to_numpy=True)
    return vector.astype('float32')
