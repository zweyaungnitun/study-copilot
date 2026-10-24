import json
import logging
import math
import os
import re
from typing import Any, Callable, Dict, List, Optional, Sequence
from collections import Counter

from app.core.config import settings
from app.core.vector_store import get_vector_store

logger = logging.getLogger("studypilot.rag")

STOP_WORDS = {
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "how", "what", "where", "when", "why", "which", "who",
    "and", "or", "it", "this", "that", "i", "me", "my", "you", "can", "explain",
}
# Calibrated on gemini-embedding-001 (768-d): on-topic questions, including keyword-free
# paraphrases, score >= 0.70; unrelated or merely adjacent topics score <= 0.64.
DENSE_THRESHOLD = 0.66
RRF_K = 60
# The keyword scorer keeps its original stop list so its calibrated 0.65 gate is unchanged.
_SYNC_STOP_WORDS = {
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "how", "what", "where", "when", "why", "which", "who",
}


def _tokenize(text: str) -> List[str]:
    """Tokenize and normalize text into lowercase tokens."""
    return re.findall(r"\b\w+\b", text.lower())


def _cosine_similarity(vec1: Dict[str, float], vec2: Dict[str, float]) -> float:
    """Compute cosine similarity between two sparse vector dicts."""
    intersection = set(vec1.keys()) & set(vec2.keys())
    if not intersection:
        return 0.0

    dot_product = sum(vec1[k] * vec2[k] for k in intersection)
    norm1 = math.sqrt(sum(v * v for v in vec1.values()))
    norm2 = math.sqrt(sum(v * v for v in vec2.values()))

    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot_product / (norm1 * norm2)


def _lexical_score(query_tokens: List[str], text: str) -> float:
    """Keyword score: cosine on term frequencies (30%) + query-term coverage with prefix stems (70%)."""
    d_tokens = _tokenize(text)
    if not d_tokens or not query_tokens:
        return 0.0
    q_counter = Counter(query_tokens)
    q_vec = {k: c / len(query_tokens) for k, c in q_counter.items()}
    d_meaningful = [t for t in d_tokens if t not in _SYNC_STOP_WORDS] or d_tokens
    d_counter = Counter(d_meaningful)
    d_vec = {k: c / len(d_meaningful) for k, c in d_counter.items()}
    cos_sim = _cosine_similarity(q_vec, d_vec)
    matched = 0
    for qt in query_tokens:
        stem = qt[:4] if len(qt) >= 4 else qt
        if any(dt == qt or (len(dt) >= 4 and dt.startswith(stem)) for dt in d_tokens):
            matched += 1
    return cos_sim * 0.3 + (matched / len(query_tokens)) * 0.7


def _bm25(query_tokens: List[str], docs_tokens: List[List[str]], k1: float = 1.4, b: float = 0.75) -> List[float]:
    n = len(docs_tokens)
    avgdl = sum(len(t) for t in docs_tokens) / max(n, 1)
    df = Counter(tok for toks in docs_tokens for tok in set(toks))
    scores = []
    for toks in docs_tokens:
        tf = Counter(toks)
        s = 0.0
        for q in set(query_tokens):
            if q not in tf:
                continue
            idf = math.log(1 + (n - df[q] + 0.5) / (df[q] + 0.5))
            s += idf * tf[q] * (k1 + 1) / (tf[q] + k1 * (1 - b + b * len(toks) / max(avgdl, 1)))
        scores.append(s)
    return scores


class RAGStore:
    """Hybrid retrieval over the learner's materials, stored in the configured ``VectorStore``."""

    DENSE_CANDIDATES = 50

    def __init__(self, persist_dir: Optional[str] = None):
        self.persist_dir = persist_dir or settings.CHROMA_PERSIST_DIR  # legacy JSON indexes live here

    @property
    def store(self):
        return get_vector_store()

    # ------------------------------------------------------------------ writes
    async def aadd_chunks(self, user_id: str, chunks: List[Dict[str, Any]]) -> int:
        """Embed (when possible) and upsert chunks. Unembedded chunks are backfilled on a later search."""
        vectors = await self._embed_docs([c.get("text", "") for c in chunks])
        model = settings.GEMINI_EMBED_MODEL if vectors else None
        for i, c in enumerate(chunks):
            c["embedding"] = vectors[i] if vectors else None
            c["embed_model"] = model
        return await self.store.upsert(user_id, chunks)

    @staticmethod
    async def _embed_docs(texts: List[str]) -> Optional[List[List[float]]]:
        from app.services.llm_client import llm_client
        vecs = await llm_client.embed(texts, "RETRIEVAL_DOCUMENT")
        return [[round(x, 5) for x in v] for v in vecs] if vecs else None

    async def _backfill(self, user_id: str, section_ids: Optional[Sequence[str]]) -> None:
        missing = await self.store.fetch(user_id, section_ids=section_ids, only_missing_embeddings=True)
        if not missing:
            return
        vecs = await self._embed_docs([d["text"] for d in missing])
        if vecs:
            await self.store.set_embeddings(user_id, {d["chunk_id"]: v for d, v in zip(missing, vecs)},
                                            settings.GEMINI_EMBED_MODEL)

    # ------------------------------------------------------------------ reads
    async def hybrid_search(
        self,
        user_id: str,
        query: str,
        top_k: int = 4,
        chapter_id: Optional[str] = None,
        lexical_threshold: float = 0.65,
        section_ids: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Hybrid retrieval: BM25 + dense embeddings fused with Reciprocal Rank Fusion.

        A chunk qualifies when it passes either the keyword-overlap gate or the semantic gate, so
        paraphrased questions still find the right notes. ``section_ids`` limits the search to those
        material sections (a chapter's sources). Falls back to keyword-only without embeddings.
        """
        if not query.strip():
            return []
        docs = await self.store.fetch(user_id, section_ids=section_ids)
        if not docs:
            return []
        from app.services.llm_client import llm_client

        q_raw = _tokenize(query)
        q_lex = [t for t in q_raw if t not in _SYNC_STOP_WORDS] or q_raw
        q_bm = [t for t in q_raw if t not in STOP_WORDS] or q_raw
        lexical = [_lexical_score(q_lex, d["text"]) for d in docs]
        bm25 = _bm25(q_bm, [[t for t in _tokenize(d["text"]) if t not in STOP_WORDS] for d in docs])

        dense: Dict[str, float] = {}
        if llm_client.is_live:
            await self._backfill(user_id, section_ids)
            qv = await llm_client.embed([query], "RETRIEVAL_QUERY")
            if qv:
                for doc, sim in await self.store.query(user_id, qv[0], self.DENSE_CANDIDATES, section_ids=section_ids):
                    dense[doc["chunk_id"]] = sim

        idx = range(len(docs))
        rrf = [0.0] * len(docs)
        for rank, i in enumerate(sorted(idx, key=lambda i: -bm25[i])):
            if bm25[i] > 0:
                rrf[i] += 1 / (RRF_K + rank + 1)
        dense_scores = [dense.get(d["chunk_id"], 0.0) for d in docs]
        for rank, i in enumerate(sorted(idx, key=lambda i: -dense_scores[i])):
            if dense_scores[i] > 0:
                rrf[i] += 1 / (RRF_K + rank + 1)

        results = []
        for i, d in enumerate(docs):
            kw_ok, sem_ok = lexical[i] >= lexical_threshold, dense_scores[i] >= DENSE_THRESHOLD
            if not (kw_ok or sem_ok):
                continue
            boost = 1.15 if chapter_id and d.get("chapter_id") == chapter_id else 1.0
            results.append({
                "chunk_id": d["chunk_id"],
                "text": d["text"],
                "filename": d.get("filename") or "unknown",
                "page_number": d.get("page_number") or 1,
                "chapter_id": d.get("chapter_id"),
                "material_id": d.get("material_id"),
                "section_id": d.get("section_id"),
                "score": round(max(lexical[i], dense_scores[i]), 4),
                "match": "both" if kw_ok and sem_ok else ("keyword" if kw_ok else "semantic"),
                "_rank": rrf[i] * boost,
            })
        if not results and not dense:
            results = self._keyword_fallback(docs, q_lex, bm25, lexical)
        results.sort(key=lambda r: r["_rank"], reverse=True)
        for r in results:
            r.pop("_rank")
        return results[:top_k]

    @staticmethod
    def _keyword_fallback(docs, q_tokens, bm25, lexical) -> List[Dict[str, Any]]:
        """Without embeddings there is no semantic gate, so paraphrased questions often miss the strict
        keyword gate. Accept the single best BM25 passage when it clearly beats the runner-up and shares
        a fair part of the question's vocabulary; unrelated questions still return nothing."""
        order = sorted(range(len(docs)), key=lambda i: -bm25[i])
        if not order or bm25[order[0]] <= 0:
            return []
        best, second = bm25[order[0]], bm25[order[1]] if len(order) > 1 else 0.0
        d = docs[order[0]]
        d_tokens = _tokenize(d["text"])
        covered = sum(1 for q in q_tokens if any(t == q or (len(t) >= 4 and t.startswith(q[:4])) for t in d_tokens))
        if best < 1.5 * second or covered / max(1, len(q_tokens)) < 0.35:
            return []
        return [{"chunk_id": d["chunk_id"], "text": d["text"], "filename": d.get("filename") or "unknown",
                 "page_number": d.get("page_number") or 1, "chapter_id": d.get("chapter_id"),
                 "material_id": d.get("material_id"), "section_id": d.get("section_id"),
                 "score": round(lexical[order[0]], 4), "match": "keyword-weak", "_rank": 1.0}]

    async def delete_material(self, user_id: str, material_id: str) -> None:
        await self.store.delete_material(user_id, material_id)

    # ------------------------------------------------------------------ legacy JSON indexes
    def legacy_files(self) -> List[str]:
        if not os.path.isdir(self.persist_dir):
            return []
        return [os.path.join(self.persist_dir, f) for f in os.listdir(self.persist_dir)
                if f.startswith("user_") and f.endswith("_materials.json")]

    async def migrate_legacy_file(self, path: str, material_for: Callable[[str, str], Any]) -> int:
        """Move one pre-vector-store JSON index into the vector store, then rename it ``*.migrated``.

        ``material_for(user_id, filename)`` returns the owning material id (or None).
        """
        user_id = os.path.basename(path)[len("user_"):-len("_materials.json")]
        try:
            with open(path, "r", encoding="utf-8") as f:
                docs = json.load(f)
        except Exception:
            logger.exception("Unreadable legacy index %s", path)
            return 0
        chunks = []
        for d in docs:
            chunks.append({
                "chunk_id": d.get("chunk_id"), "text": d.get("text", ""), "filename": d.get("filename"),
                "page_number": d.get("page_number", 1), "chunk_index": d.get("chunk_index", 0),
                "chapter_id": d.get("chapter_id"), "material_id": await material_for(user_id, d.get("filename") or ""),
                "embedding": d.get("embedding"), "embed_model": settings.GEMINI_EMBED_MODEL if d.get("embedding") else None,
            })
        n = await self.store.upsert(user_id, [c for c in chunks if c["chunk_id"]])
        os.replace(path, path + ".migrated")
        logger.info("Migrated %d legacy chunks for user %s", n, user_id)
        return n


rag_store = RAGStore()
