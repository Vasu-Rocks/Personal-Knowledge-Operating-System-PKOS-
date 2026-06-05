# Deep Logic Math Constants
MAX_CONTEXT_CHARS = 4000 # Strict hardware cutoff for 4GB VRAM prompting.

def format_context_blocks(chunks: list[dict]) -> str:
    """
    Sub-Module 3.2: Context Assembly (String Formatter)
    Packages the raw dictionaries returned natively from PostgreSQL into 
    a highly structured local string explicitly designed to prevent 'Lost in the Middle' hallucinations!
    """
    if not chunks:
        return "No relevant documents found in your database."
        
    assembled_context = ""
    
    for rank, data in enumerate(chunks):
        # Format the localized string with rigid attribution references
        block = f"--- Result {rank + 1} ---\n"
        block += f"Source: {data['filename']} (Page {data['page']})\n"
        block += f"Content: {data['text']}\n\n"
        
        # Hardware Protection Override
        if len(assembled_context) + len(block) > MAX_CONTEXT_CHARS:
            break 
            
        assembled_context += block
        
    return assembled_context.strip()
