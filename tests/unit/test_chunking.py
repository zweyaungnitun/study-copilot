def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Utility chunking text with sliding window boundary overlap."""
    if not text:
        return []
    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = text[start:end]
        chunks.append(chunk)
        if end == text_len:
            break
        start += (chunk_size - overlap)

    return chunks


def test_chunking_boundaries_and_overlap():
    sample_text = "A" * 1000
    chunks = chunk_text(sample_text, chunk_size=400, overlap=50)

    assert len(chunks) == 3
    assert len(chunks[0]) == 400
    assert len(chunks[1]) == 400
    # Overlap boundary test: start of chunk 1 matches end of chunk 0
    assert chunks[0][-50:] == chunks[1][:50]
