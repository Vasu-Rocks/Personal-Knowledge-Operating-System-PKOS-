from core.config import CONTEXT_MAX_CHARS

# Appears in the header of community-summary blocks; the prompt builder looks for it to adjust its rules.
COMMUNITY_MARKER = "generated overview of a group of related concepts"
# Header of a past-chat block (rag/memory/episodic.py); the prompt builder adds a rule for them when present.
CHAT_MARKER = "Earlier chat:"


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
        if chunk.get("via") == "community":
            header = f"[Chunk {len(used) + 1}] {chunk['filename']} ({COMMUNITY_MARKER})"
        elif chunk.get("via") == "chat":
            header = f"[Chunk {len(used) + 1}] {CHAT_MARKER} \"{chunk['filename']}\" ({chunk['page']})"
        else:
            origin = " (found via the knowledge graph)" if chunk.get("via") == "graph" else ""
            header = f"[Chunk {len(used) + 1}] Source: {chunk['filename']} (Page {chunk['page']}){origin}"
        block = f"{header}\n{chunk['text']}"
        if total + len(block) > max_chars:
            if not used:
                block = block[:max_chars]  # a single oversized chunk is truncated, never dropped
            else:
                break
        blocks.append(block)
        used.append(chunk)
        total += len(block) + 2
    return "\n\n".join(blocks), used
