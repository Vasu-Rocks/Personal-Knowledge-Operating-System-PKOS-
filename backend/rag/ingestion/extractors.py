import fitz  # PyMuPDF
import io

def extract_pdf_stream(file_stream):
    """
    Sub-Module 1.2: PDF Extraction (Generator)
    Reads spooled data dynamically. Yields (page_number, text_content).
    Prevents loading entire 500-page textbooks into a single memory list.
    """
    # Spooled file guarantees optimal mapping over huge inputs
    with fitz.open(stream=file_stream.read(), filetype="pdf") as doc:
        for page_num in range(len(doc)):
            page = doc[page_num]
            # Extra formatting preservation on PyMuPDF
            text = page.get_text("text") 
            if text.strip():
                # page_num + 1 because users expect 1-based indexing
                yield (page_num + 1, text)

def extract_text_stream(file_stream):
    """
    Sub-Module 1.2: Text/Code Extraction
    Reads standard UTF-8 files dynamically. Treats the file as a single 'page'
    but preserves exact whitespace logic essential for code snippets.
    """
    # Decoding strictly with utf-8, ignoring fatal errors gracefully
    text = file_stream.read().decode('utf-8', errors='ignore')
    if text.strip():
        yield (1, text)
