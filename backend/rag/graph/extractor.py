import httpx
import json
import logging
from core.config import OLLAMA_CHAT_URL, get_ollama_model
from rag.graph.vocab import PREDICATES, canonicalize, squash

logger = logging.getLogger(__name__)

ENTITY_CATEGORIES = ["PERSON", "ORGANIZATION", "TECHNOLOGY", "CONCEPT", "METHOD", "EVENT", "LOCATION", "OTHER"]

# Bounds are deliberate. Unconstrained, llama3.2 either returned empty arrays (with an open
# schema) or ran away with duplicates (plain JSON mode); minItems/maxItems keep it in between.
GRAPH_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "category": {"type": "string", "enum": ENTITY_CATEGORIES},
                    "description": {"type": "string"}
                },
                "required": ["name", "category", "description"]
            }
        },
        "relationships": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "predicate": {"type": "string", "enum": PREDICATES},
                    "target": {"type": "string"}
                },
                "required": ["source", "predicate", "target"]
            }
        }
    },
    "required": ["entities", "relationships"]
}

SYSTEM_PROMPT = (
    "You extract a knowledge graph from a passage of a document. "
    "List the 3-12 most important entities (" + ", ".join(ENTITY_CATEGORIES) + ") "
    "with a one-sentence description taken from the text, then the relationships between those entities. "
    "Every relationship's source and target must be an entity name from your entities list. "
    "Choose each predicate from the allowed list: USES means source uses target, USED_FOR means source is used "
    "for target, CONTAINS means source contains target. "
    "Use only facts stated in the text. Ignore page headers, licences, URLs, citations, figure and chapter "
    "references, and variable names from code listings (such as X_train, y_test, plt); extract named "
    "algorithms, classes, functions and concepts.\n"
    "Example output:\n"
    '{"entities":[{"name":"FastAPI","category":"TECHNOLOGY","description":"A Python web framework."},'
    '{"name":"Starlette","category":"TECHNOLOGY","description":"An ASGI toolkit."}],'
    '"relationships":[{"source":"FastAPI","predicate":"BUILT_ON","target":"Starlette"}]}'
)


def build_extraction_request(text: str, filename: str, previous_context: str = "") -> dict:
    """Ollama /api/chat payload for one chunk. Shared by the extractor and graph_baseline."""
    user = f"Document: {filename}\n\n"
    if previous_context:
        user += f"[PRECEDING TEXT - for resolving pronouns only]\n{previous_context}\n\n"
    user += f"[PASSAGE TO EXTRACT FROM]\n{text}"
    return {
        "model": get_ollama_model(),
        "stream": False,
        "format": GRAPH_SCHEMA,
        "keep_alive": "15m",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "options": {
            "temperature": 0.0,  # Forces deterministic extraction
            "num_ctx": 2048,  # Caps VRAM usage; 4096 measured ~30% slower per token on the RTX 3050
            "num_predict": 1024,  # Bounds runaway generations (observed >300s without a cap)
        },
    }


def ground_extraction(data: dict, *texts: str) -> dict:
    """
    Drops entities and relationship endpoints whose name never appears in the source text.
    Small models parrot the prompt example or invent entities when a chunk has little content.
    """
    # Compared in squashed form so 'tf-idf' in the text grounds 'TF–IDF' from the model.
    haystack = " ".join(squash(t) for t in texts if t)
    entities = [
        e for e in data.get("entities", [])
        if isinstance(e, dict) and canonicalize(e.get("name")) and canonicalize(e["name"]) in haystack
    ]
    # Endpoints are grounded against the text, not the entity list: the reconciler adds the
    # entities a relationship names but the model forgot to list.
    relationships = [
        r for r in data.get("relationships", [])
        if isinstance(r, dict)
        and canonicalize(r.get("source")) and canonicalize(r["source"]) in haystack
        and canonicalize(r.get("target")) and canonicalize(r["target"]) in haystack
    ]
    return {"entities": entities, "relationships": relationships}


async def extract_chunk(client: httpx.AsyncClient, text: str, filename: str, previous_context: str = "") -> dict | None:
    """
    Phase 2: Offline Triplet Extraction for one chunk.
    Returns grounded {"entities", "relationships"}, or None when the model produced invalid JSON.
    Connection and HTTP errors propagate so the worker can fail the job (it is resumable).
    """
    response = await client.post(OLLAMA_CHAT_URL, json=build_extraction_request(text, filename, previous_context))
    response.raise_for_status()
    content = response.json().get("message", {}).get("content", "")
    try:
        return ground_extraction(json.loads(content), text, previous_context)
    except json.JSONDecodeError:
        logger.warning(f"Ollama returned invalid JSON: {content[:200]}")
        return None
