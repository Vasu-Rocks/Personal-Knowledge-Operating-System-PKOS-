import re
import unicodedata

def clean_text(text: str, file_extension: str) -> str:
    """
    Cleans extracted text based on its source file type.
    """
    # 1. Base Normalization (Applies to everything)
    text = unicodedata.normalize('NFKD', text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text) # Remove control chars
    
    # 2. Token-Wasting Artifact Removal (Applies to everything)
    # Replaces long URLs with a token-friendly placeholder
    text = re.sub(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*', '[URL]', text)
    
    # --- BRANCH LOGIC based on File Type ---
    
    if file_extension in ['.py', '.js']:
        # CODE FILES: Be extremely gentle. Do NOT touch indentation.
        # Only remove excessive blank lines (more than 2)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
    else:
        # PDFs, TXT, MD: Aggressive Natural Language Cleaning
        
        # Fix broken hyphenated words at line breaks (PDFs)
        text = re.sub(r'-\n+', '', text)
        
        # Collapse excessive newlines
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Collapse excessive spaces (DANGEROUS FOR CODE, SAFE FOR PDF)
        text = re.sub(r'[ \t]+', ' ', text)
        
        # Basic Gibberish check: If a block has too many special symbols, it might be a broken chart.
        # (Optional: you can implement a ratio check here if needed later)

    final_text = text.strip()
    
    # 3. Ghost Chunk Prevention
    # If after all cleaning, the text is less than 50 characters, it's useless noise.
    if len(final_text) < 50:
        return "" # Return empty string so the pipeline ignores it
        
    return final_text
