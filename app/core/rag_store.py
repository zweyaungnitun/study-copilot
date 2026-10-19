import json
import math
import os
import re
from typing import Any, Dict, List, Optional
from collections import Counter

from app.core.config import settings


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


class RAGStore:
    """Local vector and chunk retrieval store for StudyPilot with persistence."""

    def __init__(self, persist_dir: Optional[str] = None):
        self.persist_dir = persist_dir or settings.CHROMA_PERSIST_DIR
        os.makedirs(self.persist_dir, exist_ok=True)

    def _get_collection_path(self, user_id: str) -> str:
        return os.path.join(self.persist_dir, f"user_{user_id}_materials.json")

    def _load_collection(self, user_id: str) -> List[Dict[str, Any]]:
        path = self._get_collection_path(user_id)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_collection(self, user_id: str, docs: List[Dict[str, Any]]) -> None:
        path = self._get_collection_path(user_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(docs, f, ensure_ascii=False, indent=2)

    def add_chunks(self, user_id: str, chunks: List[Dict[str, Any]]) -> int:
        """Add and persist document chunks for user."""
        docs = self._load_collection(user_id)
        existing_ids = {d.get("chunk_id") for d in docs}

        added = 0
        for chunk in chunks:
            if chunk.get("chunk_id") not in existing_ids:
                docs.append(chunk)
                added += 1

        self._save_collection(user_id, docs)
        return added

    def search(
        self,
        user_id: str,
        query: str,
        top_k: int = 4,
        similarity_threshold: float = 0.65,
    ) -> List[Dict[str, Any]]:
        """
        Search user collection using cosine similarity on term-frequency vectors.
        Returns top scoring chunks matching or exceeding similarity_threshold.
        """
        docs = self._load_collection(user_id)
        if not docs or not query.strip():
            return []

        STOP_WORDS = {
            "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by", "from",
            "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
            "do", "does", "did", "how", "what", "where", "when", "why", "which", "who",
        }

        raw_query_tokens = _tokenize(query)
        query_tokens = [t for t in raw_query_tokens if t not in STOP_WORDS]
        if not query_tokens:
            query_tokens = raw_query_tokens
        if not query_tokens:
            return []

        q_counter = Counter(query_tokens)
        q_len = len(query_tokens)
        q_vec = {k: count / q_len for k, count in q_counter.items()}

        results = []
        for doc in docs:
            doc_text = doc.get("text", "")
            d_tokens = _tokenize(doc_text)
            if not d_tokens:
                continue

            d_meaningful = [t for t in d_tokens if t not in STOP_WORDS] or d_tokens
            d_counter = Counter(d_meaningful)
            d_len = len(d_meaningful)
            d_vec = {k: count / d_len for k, count in d_counter.items()}

            cos_sim = _cosine_similarity(q_vec, d_vec)

            # Keyword matching with prefix/stem support for words >= 4 chars
            matched_q = 0
            for qt in query_tokens:
                stem = qt[:4] if len(qt) >= 4 else qt
                if any(dt == qt or (len(dt) >= 4 and dt.startswith(stem)) for dt in d_tokens):
                    matched_q += 1

            overlap_ratio = matched_q / len(query_tokens)
            score = (cos_sim * 0.3) + (overlap_ratio * 0.7)

            if score >= similarity_threshold:
                results.append({
                    "chunk_id": doc.get("chunk_id"),
                    "text": doc_text,
                    "filename": doc.get("filename", "unknown"),
                    "page_number": doc.get("page_number", 1),
                    "chapter_id": doc.get("chapter_id"),
                    "score": round(score, 4),
                })

        # Sort descending by relevance score
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def clear_user_collection(self, user_id: str) -> None:
        """Clear all materials for user."""
        path = self._get_collection_path(user_id)
        if os.path.exists(path):
            os.remove(path)


rag_store = RAGStore()
