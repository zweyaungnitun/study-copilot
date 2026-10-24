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


def test_semantic_chunks_keep_whole_sentences():
    from app.services.ingestion_service import semantic_chunks
    text = " ".join(f"Sentence number {i} explains something." for i in range(60))
    chunks = semantic_chunks(text, target=300, overlap=80)
    assert len(chunks) > 1 and all(len(c) <= 300 for c in chunks)
    assert all(c.rstrip().endswith(".") and c[0].isupper() for c in chunks)
    first_tail = chunks[0].split(". ")[-1]
    assert first_tail in chunks[1]  # overlap is a whole sentence
