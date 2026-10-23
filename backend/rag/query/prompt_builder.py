import re
from core.config import GRAPH_CONTEXT_MAX_CHARS
from rag.query.retriever import COMMUNITY_MARKER

def build_rag_prompt(user_query: str, retrieved_context: str, graph_data: dict = None) -> list[dict[str, str]]:
    """
    Sub-Module 3.3: Prompt Engineering
    Constructs a strictly bounded instruction set for the quantized LLM.
    Applies negative constraints and structural ChatML/Llama-3 templating logic.
    """
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
    if not retrieved_context and not graph_context:
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

    # 2. Complete Structurally Bounded Generator Template
    system_content = f"""You are the strict, analytical AI assistant for the PKOS (Personal Knowledge Operating System).
Your core directive is to answer the user's question ONLY using the provided CONTEXT.

CRITICAL INSTRUCTIONS:
1. If the exact answer is not contained within the CONTEXT, you must output exactly: "I cannot find the answer in your documents."
2. Do NOT use outside knowledge. Do NOT make up information.
3. You MUST cite your claims using the identifiers provided, for example: [Chunk 1] or [Graph Entity: FastAPI].
4. Format your answer thoughtfully using Markdown, placing citations in italics.
{overview_rule}
========== START CONTEXT ==========
{retrieved_context}
{graph_context}
=========== END CONTEXT ==========="""

    return [
        {"role": "system", "content": system_content.strip()},
        {"role": "user", "content": user_query}
    ]
