from langchain_text_splitters import RecursiveCharacterTextSplitter

def split_text_into_chunks(clean_text: str) -> list[str]:
    """
    Sub-Module 1.4: Document Chunking (Segmentation)
    Implements mathematical constraints requested for 4-bit Quantized LLMs (~4GB VRAM).
    Character size 1200 yields roughly ~300 tokens optimally representing context bounds.
    """
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1200,
        chunk_overlap=200,
        separators=["\n\n", "\n", ".", " ", ""]
    )
    return text_splitter.split_text(clean_text)
