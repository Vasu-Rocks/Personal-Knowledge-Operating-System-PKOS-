from core.config import CONTEXT_MAX_CHARS


def format_context_blocks(chunks: list[dict], max_chars: int = CONTEXT_MAX_CHARS) -> tuple[str, list[dict]]:
    """
    Sub-Module 3.2: Context Assembly (String Formatter)
    Labels each chunk "[Chunk N]" to match the citation format the prompt asks for, and stops at the character
    budget (4GB VRAM). Returns (context_text, chunks_used): N is the 1-based index into chunks_used, so callers
    must send chunks_used, not the original list, as sources.
    """
    if not chunks:
        return "", []

    blocks, used, total = [], [], 0
    for chunk in chunks:
        origin = " (found via the knowledge graph)" if chunk.get("via") == "graph" else ""
        block = f"[Chunk {len(used) + 1}] Source: {chunk['filename']} (Page {chunk['page']}){origin}\n{chunk['text']}"
        if total + len(block) > max_chars:
            if not used:
                block = block[:max_chars]  # a single oversized chunk is truncated, never dropped
            else:
                break
        blocks.append(block)
        used.append(chunk)
        total += len(block) + 2
    return "\n\n".join(blocks), used
