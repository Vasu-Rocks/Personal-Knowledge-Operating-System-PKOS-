import httpx
import logging
from core.config import get_ollama_model
from core.llm import LLMSettings, chat_text, extract_json
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


def build_extraction_messages(text: str, filename: str, previous_context: str = "") -> list[dict]:
    user = f"Document: {filename}\n\n"
    if previous_context:
        user += f"[PRECEDING TEXT - for resolving pronouns only]\n{previous_context}\n\n"
    user += f"[PASSAGE TO EXTRACT FROM]\n{text}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def build_extraction_request(text: str, filename: str, previous_context: str = "") -> dict:
    """Ollama /api/chat payload for one chunk (used by the graph_baseline timing script)."""
    return {
        "model": get_ollama_model(),
        "stream": False,
        "format": GRAPH_SCHEMA,
        "keep_alive": "15m",
        "messages": build_extraction_messages(text, filename, previous_context),
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


async def extract_chunk(client: httpx.AsyncClient, text: str, filename: str, previous_context: str = "",
                        settings: LLMSettings | None = None) -> dict | None:
    """
    Phase 2: Offline Triplet Extraction for one chunk, with the user's chosen provider (Ollama by default).
    Returns grounded {"entities", "relationships"}, or None when the model produced invalid JSON.
    Provider errors (LLMError) propagate so the worker can fail the job (it is resumable).
    """
    s = settings or LLMSettings()
    content = await chat_text(
        s, build_extraction_messages(text, filename, previous_context), schema=GRAPH_SCHEMA,
        temperature=0.0,
        num_ctx=2048,  # Caps VRAM usage on Ollama; 4096 measured ~30% slower per token on the RTX 3050
        max_tokens=1024,  # Bounds runaway generations (observed >300s without a cap)
        client=client)
    data = extract_json(content)
    if data is None:
        logger.warning(f"{s.label} returned invalid JSON: {content[:200]}")
        return None
    return ground_extraction(data, text, previous_context)
