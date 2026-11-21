from rag.query.prompt_builder import build_rag_prompt
from rag.query.retriever import COMMUNITY_MARKER, format_context_blocks


def chunk(i, text="body", via="vector", filename="a.pdf", page=1):
    return {"chunk_id": i, "text": text, "via": via, "filename": filename, "page": page}


def test_chunks_are_labelled_sequentially():
    ctx, used = format_context_blocks([chunk(1), chunk(2, via="graph")])
    assert "[Chunk 1] Source: a.pdf (Page 1)" in ctx
    assert "[Chunk 2]" in ctx and "found via the knowledge graph" in ctx
    assert len(used) == 2


def test_budget_drops_later_chunks_and_returns_used_only():
    ctx, used = format_context_blocks([chunk(1, "x" * 80), chunk(2, "y" * 80)], max_chars=120)
    assert len(used) == 1 and "[Chunk 2]" not in ctx


def test_single_oversized_chunk_is_truncated_not_dropped():
    ctx, used = format_context_blocks([chunk(1, "x" * 500)], max_chars=100)
    assert len(used) == 1 and len(ctx) == 100


def test_empty_chunks():
    assert format_context_blocks([]) == ("", [])


def test_community_block_header():
    ctx, _ = format_context_blocks([chunk(1, via="community")])
    assert COMMUNITY_MARKER in ctx


def test_prompt_strips_triple_equals_but_keeps_single():
    msgs = build_rag_prompt("what is a == b ==== c", "ctx")
    assert msgs[-1]["content"] == "what is a == b  c"


def test_prompt_without_any_context_uses_fallback():
    msgs = build_rag_prompt("anything", "", {})
    assert "no uploaded documents" in msgs[0]["content"]


def test_seed_only_nodes_reach_the_prompt():
    graph = {"nodes": [{"id": "1", "name": "FastAPI", "description": "web framework"}], "links": []}
    system = build_rag_prompt("q", "ctx", graph)[0]["content"]
    assert "=== KNOWLEDGE GRAPH ENTITIES ===" in system and "FastAPI: web framework" in system


def test_links_render_with_descriptions():
    graph = {
        "nodes": [{"id": "1", "name": "A", "description": ""}, {"id": "2", "name": "B", "description": "bee"}],
        "links": [{"source": "1", "target": "2", "predicate": "USES", "description": "often"}],
    }
    system = build_rag_prompt("q", "ctx", graph)[0]["content"]
    assert "(A) --[USES (often)]--> (B: bee)" in system


def test_overview_rule_only_for_community_context():
    with_rule = build_rag_prompt("q", f"[Chunk 1] x ({COMMUNITY_MARKER})")[0]["content"]
    without = build_rag_prompt("q", "[Chunk 1] x")[0]["content"]
    assert "5. Blocks marked" in with_rule and "5. Blocks marked" not in without
