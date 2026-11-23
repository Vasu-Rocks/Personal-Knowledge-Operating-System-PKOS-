import re
from core.config import GRAPH_CONTEXT_MAX_CHARS
from rag.query.retriever import COMMUNITY_MARKER

MEMORY_LABELS = {"preference": "Preference", "fact": "Fact", "conclusion": "Kept conclusion"}


def build_rag_prompt(user_query: str, retrieved_context: str, graph_data: dict = None,
                     history: list[dict[str, str]] | None = None, summary: str | None = None,
                     memories: list[dict] | None = None) -> list[dict[str, str]]:
    """
    Sub-Module 3.3: Prompt Engineering
    Constructs a strictly bounded instruction set for the quantized LLM.
    Applies negative constraints and structural ChatML/Llama-3 templating logic.
    history: earlier turns of this chat as user/assistant messages (rag/memory/stm.py); summary: a summary of turns
    before those. Both only help the model understand the question; without them the prompt is unchanged.
    memories: the user's saved notes (rag/memory/ltm.py), in a section of their own outside CONTEXT; facts among them may
    answer a question about the user (docs/07_MEMORY_PLAN.md, decision Q5). Without them the prompt is unchanged.
    """
    memories = memories or []
    about_user = any(m["kind"] != "preference" for m in memories)
    if graph_data is None:
        graph_data = {}
        
    # Defensive Sanitizer: Removes 3 or more consecutive '=' signs to prevent injection,
    # but completely preserves single '=' for math and coding questions!
    user_query = re.sub(r'={3,}', '', user_query).strip()
    
    # Assemble Graph Context
    graph_context = ""
    if graph_data and graph_data.get("nodes"):
        # Map node IDs to names for readable prompts
        node_map = {n["id"]: n for n in graph_data.get("nodes", [])}
        graph_lines = []
        linked_ids = set()
        for link in graph_data.get("links", []):
            linked_ids.update((link["source"], link["target"]))
            source_node = node_map.get(link["source"], {})
            source = source_node.get("name", "Unknown")
            source_desc = source_node.get("description", "")
            
            target_node = node_map.get(link["target"], {})
            target = target_node.get("name", "Unknown")
            target_desc = target_node.get("description", "")
            
            source_text = f"{source}: {source_desc}" if source_desc else source
            target_text = f"{target}: {target_desc}" if target_desc else target
            
            # Format: (Source: Source Desc) --[PREDICATE (Relation Description)]--> (Target: Target Desc)
            relation = f"{link['predicate']} ({link['description']})" if link.get("description") else link["predicate"]
            line = f"({source_text}) --[{relation}]--> ({target_text})"
            if sum(len(l) + 1 for l in graph_lines) + len(line) > GRAPH_CONTEXT_MAX_CHARS:
                break  # edges arrive ranked best-first, so the tail is what gets dropped
            graph_lines.append(line)
            
        if graph_lines:
            graph_context = "\n=== KNOWLEDGE GRAPH RELATIONSHIPS ===\n" + "\n".join(graph_lines) + "\n"

        # Seed entities with no edges still carry a description worth giving the LLM.
        entity_lines = [
            f"{n['name']}: {n['description']}" if n.get("description") else n["name"]
            for n in graph_data["nodes"]
            if n["id"] not in linked_ids
        ]
        if entity_lines:
            graph_context += "\n=== KNOWLEDGE GRAPH ENTITIES ===\n" + "\n".join(entity_lines) + "\n"

    # 1. Fallback Guardrail: Intercepts failed FAISS retrieval natively.
    if not retrieved_context and not graph_context and not about_user:
        return [
            {"role": "system", "content": "You are the strict, analytical AI assistant for the PKOS system. The user asked a question, but there are no uploaded documents available to answer it."},
            {"role": "user", "content": f"System Request: The user asked '{user_query}'. Politely inform them that there are no documents or graph connections in the database containing this answer. Format your response clearly in Markdown."}
        ]

    # Community summaries (global search) are generated overviews of whole topic areas. For overview questions the
    # answer is a synthesis of them, so the strict "exact answer" refusal rule would make the model refuse wrongly.
    overview_rule = ""
    if COMMUNITY_MARKER in retrieved_context:
        overview_rule = (
            "5. Blocks marked \"generated overview of a group of related concepts\" are valid evidence. For overview or "
            "theme questions, combine them (and any other blocks) into a short structured answer and cite each one.\n"
        )

    # Citation examples are taken from this CONTEXT. A fixed example ("[Graph Entity: FastAPI]") was copied verbatim
    # by small models into answers that had nothing to do with FastAPI.
    examples = []
    if retrieved_context:
        examples.append("[Chunk 1]")
    entity = next((n["name"] for n in (graph_data or {}).get("nodes", []) if n.get("name") and n["name"] in graph_context), None)
    if entity:
        examples.append(f"[Graph Entity: {entity}]")
    if examples:
        citation_rule = (
            f"3. You MUST cite your claims using only identifiers that appear in the CONTEXT, for example: "
            f"{' or '.join(examples)}. Never cite a chunk number or entity that is not in the CONTEXT."
        )
    else:
        citation_rule = "3. Cite claims only with identifiers that appear in the CONTEXT; there are none here, so cite nothing."

    # Long-term memories: the user's own notes, outside CONTEXT.
    no_answer_rule = ('1. If the exact answer is not contained within the CONTEXT, you must output exactly: '
                      '"I cannot find the answer in your documents."')
    memory_block = ""
    if memories:
        lines = [f"- {MEMORY_LABELS.get(m['kind'], 'Note')}: {re.sub(r'={3,}', '', m['text']).strip()}" for m in memories]
        guidance = "Follow the preferences when you write the answer. Use the notes to understand the question."
        if about_user:
            # Where the answer came from is shown by the app ("Answered from your saved memories"): llama3.2 ignored
            # an instruction to say so itself in 3 of 3 tries.
            guidance += " A question about the user themselves may be answered from these notes."
            no_answer_rule = ('1. If the exact answer is not contained within the CONTEXT (or, for a question about the '
                              'user themselves, in ABOUT THE USER), you must output exactly: '
                              '"I cannot find the answer in your documents."')
        guidance += " Never use the notes as facts about the documents, and never cite them as a chunk."
        memory_block = ("\nABOUT THE USER (notes the user saved in PKOS; they are not documents):\n"
                        + "\n".join(lines) + "\n" + guidance + "\n")

    # Conversation memory: earlier turns are for understanding the question, never a source of facts.
    memory_rule, summary_block = "", ""
    if history or summary:
        memory_rule = (
            f"{6 if overview_rule else 5}. The earlier messages of this conversation are there only so you understand "
            "what the user means (for example what \"it\" or \"the second one\" refers to). Facts in your answer must "
            "still come from the CONTEXT, with citations.\n"
        )
    if summary:
        summary = re.sub(r'={3,}', '', summary).strip()
        summary_block = f"\nEARLIER IN THIS CONVERSATION (summary):\n{summary}\n"

    # Without this sentence llama3.2 refused "Summarise my notes on photosynthesis" with the notes in CONTEXT; with it,
    # 30/30 summary/explain/direct questions were answered and 15/15 unanswerable ones still refused (2026-11-23).
    no_answer_rule += (" But requests to summarise, explain, list or give an overview of something the CONTEXT covers "
                       "are NOT refused: answer them from the CONTEXT.")

    # 2. Complete Structurally Bounded Generator Template
    system_content = f"""You are the strict, analytical AI assistant for the PKOS (Personal Knowledge Operating System).
Your core directive is to answer the user's question ONLY using the provided CONTEXT.

CRITICAL INSTRUCTIONS:
{no_answer_rule}
2. Do NOT use outside knowledge. Do NOT make up information.
{citation_rule}
4. Format your answer thoughtfully using Markdown, placing citations in italics.
{overview_rule}{memory_rule}{summary_block}{memory_block}
========== START CONTEXT ==========
{retrieved_context}
{graph_context}
=========== END CONTEXT ==========="""

    return [
        {"role": "system", "content": system_content.strip()},
        *(history or []),
        {"role": "user", "content": user_query}
    ]
