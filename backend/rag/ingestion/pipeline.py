from .extractors import extract_pdf_stream, extract_text_stream
from .cleaner import clean_text
from .chunker import split_text_into_chunks

def process_file_stream(file_stream, filename: str, doc_id: str) -> list[dict]:
    """
    Sub-Module 1.5: Metadata Attachment & Orchestrator
    Manages the sequential pipeline from continuous Byte -> Generator -> Clean -> Chunk -> Tag.
    """
    # 1. Routing Validator
    extension = filename.split(".")[-1].lower()
    
    if extension == "pdf":
        page_generator = extract_pdf_stream(file_stream)
    elif extension in ["txt", "md", "py", "js"]:
        page_generator = extract_text_stream(file_stream)
    else:
        raise ValueError(f"Unsupported extension: {extension}")

    # 2. Sequential Generator Logic
    # Pulls exactly 1 page into RAM. Cleans it. Chunks it. Attaches Metadata. Releases Page memory.
    global_chunk_index = 0
    
    for page_num, raw_content in page_generator:
        # Pass to 1.3
        cleaned = clean_text(raw_content, f".{extension}")
        if not cleaned:
            continue
            
        # Pass to 1.4
        chunks = split_text_into_chunks(cleaned)
        
        # Action 1.5
        for piece in chunks:
            payload = {
                "text": piece,
                "metadata": {
                    "document_id": doc_id,
                    "file_name": filename,
                    "chunk_index": global_chunk_index,
                    "page_number": page_num
                }
            }
            yield payload
            global_chunk_index += 1
