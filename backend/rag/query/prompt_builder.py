import re

def build_rag_prompt(user_query: str, retrieved_context: str) -> list[dict[str, str]]:
    """
    Sub-Module 3.3: Prompt Engineering
    Constructs a strictly bounded instruction set for the quantized LLM.
    Applies negative constraints and structural ChatML/Llama-3 templating logic.
    """
    # Defensive Sanitizer: Removes 3 or more consecutive '=' signs to prevent injection,
    # but completely preserves single '=' for math and coding questions!
    user_query = re.sub(r'={3,}', '', user_query).strip()
    
    # 1. Fallback Guardrail: Intercepts failed FAISS retrieval natively.
    if not retrieved_context or retrieved_context == "No relevant documents found in your database.":
        return [
            {"role": "system", "content": "You are the strict, analytical AI assistant for the PKOS system. The user asked a question, but there are no uploaded documents available to answer it."},
            {"role": "user", "content": f"System Request: The user asked '{user_query}'. Politely inform them that there are no documents in the database containing this answer. Format your response clearly in Markdown."}
        ]

    # 2. Complete Structurally Bounded Generator Template
    system_content = f"""You are the strict, analytical AI assistant for the PKOS (Personal Knowledge Operating System).
Your core directive is to answer the user's question ONLY using the provided CONTEXT.

CRITICAL INSTRUCTIONS:
1. If the exact answer is not contained within the CONTEXT, you must output exactly: "I cannot find the answer in your documents."
2. Do NOT use outside knowledge. Do NOT make up information.
3. Always cite the Source and Page number provided in the CONTEXT when generating your answer.
4. Format your answer thoughtfully using Markdown, placing citations in italics.

========== START CONTEXT ==========
{retrieved_context}
=========== END CONTEXT ==========="""

    return [
        {"role": "system", "content": system_content.strip()},
        {"role": "user", "content": user_query}
    ]
