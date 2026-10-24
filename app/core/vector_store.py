"""Chunk + embedding storage behind one interface: Chroma (embedded, MVP/dev) or pgvector (production).

Every operation is scoped to one user, and filters by material/section so retrieval can be limited to
the sections a chapter covers. Chunks that were indexed without an embedding (offline, or the API
failed) are stored with ``embedded=False`` and backfilled later; dense queries skip them.
"""
import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.config import settings

logger = logging.getLogger("studypilot.vectors")

META_FIELDS = ("material_id", "section_id", "filename", "page_number", "chunk_index", "chapter_id", "embed_model")


def _doc(chunk_id: str, text: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    return {"chunk_id": chunk_id, "text": text or "", **{k: meta.get(k) for k in META_FIELDS},
            "embedded": bool(meta.get("embedded"))}


class VectorStore:
    async def upsert(self, user_id: str, chunks: Sequence[Dict[str, Any]]) -> int: ...
    async def fetch(self, user_id: str, section_ids: Optional[Sequence[str]] = None,
                    material_ids: Optional[Sequence[str]] = None, only_missing_embeddings: bool = False) -> List[Dict[str, Any]]: ...
    async def query(self, user_id: str, vector: Sequence[float], k: int,
                    section_ids: Optional[Sequence[str]] = None) -> List[Tuple[Dict[str, Any], float]]: ...
    async def set_embeddings(self, user_id: str, vectors: Dict[str, Sequence[float]], model: str) -> None: ...
    async def delete_material(self, user_id: str, material_id: str) -> None: ...
    async def delete_user(self, user_id: str) -> None: ...
    async def count(self, user_id: str) -> int: ...


# ---------------------------------------------------------------------------- Chroma
class ChromaVectorStore(VectorStore):
    """Persistent embedded Chroma, one collection per user (cosine HNSW)."""

    def __init__(self, path: Optional[str] = None):
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        self.path = path or settings.CHROMA_PERSIST_DIR
        # Never send telemetry about learners' material collections.
        self.client = chromadb.PersistentClient(path=self.path, settings=ChromaSettings(anonymized_telemetry=False))
        self._lock = asyncio.Lock()  # embedded Chroma is a single writer

    def _col(self, user_id: str):
        name = "u_" + re.sub(r"[^a-zA-Z0-9._-]", "", user_id)
        return self.client.get_or_create_collection(name, embedding_function=None, metadata={"hnsw:space": "cosine"})

    @staticmethod
    def _where(section_ids=None, material_ids=None, extra: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        conds: List[Dict[str, Any]] = []
        if section_ids is not None:
            conds.append({"section_id": {"$in": list(section_ids) or ["__none__"]}})
        if material_ids is not None:
            conds.append({"material_id": {"$in": list(material_ids) or ["__none__"]}})
        if extra:
            conds.extend({k: v} for k, v in extra.items())
        return None if not conds else conds[0] if len(conds) == 1 else {"$and": conds}

    @staticmethod
    def _placeholder() -> List[float]:
        return [1.0] + [0.0] * (settings.EMBED_DIM - 1)

    async def upsert(self, user_id, chunks):
        if not chunks:
            return 0

        def run():
            ids, embs, docs, metas = [], [], [], []
            for c in chunks:
                emb = c.get("embedding")
                ok = bool(emb) and len(emb) == settings.EMBED_DIM
                ids.append(c["chunk_id"])
                embs.append(list(emb) if ok else self._placeholder())
                docs.append(c.get("text", ""))
                metas.append({**{k: c[k] for k in META_FIELDS if c.get(k) is not None}, "embedded": ok})
            col = self._col(user_id)
            for i in range(0, len(ids), 500):
                col.upsert(ids=ids[i:i + 500], embeddings=embs[i:i + 500], documents=docs[i:i + 500], metadatas=metas[i:i + 500])
            return len(ids)

        async with self._lock:
            return await asyncio.to_thread(run)

    async def fetch(self, user_id, section_ids=None, material_ids=None, only_missing_embeddings=False):
        def run():
            res = self._col(user_id).get(
                where=self._where(section_ids, material_ids, {"embedded": False} if only_missing_embeddings else None),
                include=["documents", "metadatas"])
            return [_doc(i, d, m or {}) for i, d, m in zip(res["ids"], res["documents"], res["metadatas"])]
        return await asyncio.to_thread(run)

    async def query(self, user_id, vector, k, section_ids=None):
        def run():
            col = self._col(user_id)
            n = col.count()
            if not n:
                return []
            res = col.query(query_embeddings=[list(vector)], n_results=min(k, n),
                            where=self._where(section_ids, None, {"embedded": True}), include=["documents", "metadatas", "distances"])
            return [(_doc(i, d, m or {}), 1.0 - dist) for i, d, m, dist in
                    zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0])]
        try:
            return await asyncio.to_thread(run)
        except Exception:  # e.g. the filter matches nothing embedded
            logger.debug("Chroma query failed", exc_info=True)
            return []

    async def set_embeddings(self, user_id, vectors, model):
        def run():
            col = self._col(user_id)
            ids = [i for i, v in vectors.items() if len(v) == settings.EMBED_DIM]
            if not ids:
                return
            current = col.get(ids=ids, include=["metadatas"])
            metas = {i: m for i, m in zip(current["ids"], current["metadatas"])}
            col.update(ids=ids, embeddings=[list(vectors[i]) for i in ids],
                       metadatas=[{**(metas.get(i) or {}), "embedded": True, "embed_model": model} for i in ids])
        async with self._lock:
            await asyncio.to_thread(run)

    async def delete_material(self, user_id, material_id):
        async with self._lock:
            await asyncio.to_thread(lambda: self._col(user_id).delete(where={"material_id": material_id}))

    async def delete_user(self, user_id):
        def run():
            try:
                self.client.delete_collection("u_" + re.sub(r"[^a-zA-Z0-9._-]", "", user_id))
            except Exception:
                pass
        async with self._lock:
            await asyncio.to_thread(run)

    async def count(self, user_id):
        return await asyncio.to_thread(lambda: self._col(user_id).count())


# ---------------------------------------------------------------------------- pgvector
class PgVectorStore(VectorStore):
    """``rag_chunks`` table in PostgreSQL with the pgvector extension and an HNSW cosine index."""

    def __init__(self, url: Optional[str] = None):
        from sqlalchemy.ext.asyncio import create_async_engine
        self.url = url or settings.PGVECTOR_URL or settings.DATABASE_URL
        if not self.url.startswith("postgresql"):
            raise RuntimeError("VECTOR_BACKEND=pgvector needs a PostgreSQL PGVECTOR_URL or DATABASE_URL")
        self.engine = create_async_engine(self.url, pool_pre_ping=True)
        self._ready = False

    async def _init(self):
        if self._ready:
            return
        from sqlalchemy import text
        dim = settings.EMBED_DIM
        async with self.engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, material_id TEXT, section_id TEXT,
                    filename TEXT, page_number INT, chunk_index INT, chapter_id TEXT, embed_model TEXT,
                    text TEXT NOT NULL, embedding vector({dim}))"""))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS rag_chunks_user ON rag_chunks (user_id, material_id)"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS rag_chunks_section ON rag_chunks (user_id, section_id)"))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS rag_chunks_hnsw ON rag_chunks USING hnsw (embedding vector_cosine_ops)"))
        self._ready = True

    @staticmethod
    def _vec(v: Sequence[float]) -> str:
        return "[" + ",".join(f"{float(x):.6f}" for x in v) + "]"

    @staticmethod
    def _filters(section_ids, material_ids, params: Dict[str, Any]) -> str:
        sql = ""
        if section_ids is not None:
            sql += " AND section_id = ANY(:sids)"
            params["sids"] = list(section_ids)
        if material_ids is not None:
            sql += " AND material_id = ANY(:mids)"
            params["mids"] = list(material_ids)
        return sql

    @staticmethod
    def _row(r) -> Dict[str, Any]:
        m = r._mapping
        return _doc(m["id"], m["text"], {**dict(m), "embedded": m.get("has_emb")})

    async def upsert(self, user_id, chunks):
        from sqlalchemy import text
        await self._init()
        rows = []
        for c in chunks:
            emb = c.get("embedding")
            rows.append({"id": c["chunk_id"], "user_id": user_id, "text": c.get("text", ""),
                         "emb": self._vec(emb) if emb and len(emb) == settings.EMBED_DIM else None,
                         **{k: c.get(k) for k in META_FIELDS}})
        if not rows:
            return 0
        async with self.engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO rag_chunks (id, user_id, material_id, section_id, filename, page_number, chunk_index,
                                        chapter_id, embed_model, text, embedding)
                VALUES (:id, :user_id, :material_id, :section_id, :filename, :page_number, :chunk_index,
                        :chapter_id, :embed_model, :text, CAST(:emb AS vector))
                ON CONFLICT (id) DO UPDATE SET text = EXCLUDED.text, embedding = EXCLUDED.embedding,
                    section_id = EXCLUDED.section_id, material_id = EXCLUDED.material_id,
                    page_number = EXCLUDED.page_number, embed_model = EXCLUDED.embed_model"""), rows)
        return len(rows)

    async def fetch(self, user_id, section_ids=None, material_ids=None, only_missing_embeddings=False):
        from sqlalchemy import text
        await self._init()
        params: Dict[str, Any] = {"u": user_id}
        sql = ("SELECT id, text, material_id, section_id, filename, page_number, chunk_index, chapter_id, embed_model, "
               "embedding IS NOT NULL AS has_emb FROM rag_chunks WHERE user_id = :u")
        sql += self._filters(section_ids, material_ids, params)
        if only_missing_embeddings:
            sql += " AND embedding IS NULL"
        async with self.engine.connect() as conn:
            return [self._row(r) for r in (await conn.execute(text(sql + " ORDER BY material_id, chunk_index"), params))]

    async def query(self, user_id, vector, k, section_ids=None):
        from sqlalchemy import text
        await self._init()
        params: Dict[str, Any] = {"u": user_id, "v": self._vec(vector), "k": k}
        sql = ("SELECT id, text, material_id, section_id, filename, page_number, chunk_index, chapter_id, embed_model, "
               "TRUE AS has_emb, 1 - (embedding <=> CAST(:v AS vector)) AS sim FROM rag_chunks "
               "WHERE user_id = :u AND embedding IS NOT NULL")
        sql += self._filters(section_ids, None, params)
        async with self.engine.connect() as conn:
            rows = (await conn.execute(text(sql + " ORDER BY embedding <=> CAST(:v AS vector) LIMIT :k"), params)).all()
        return [(self._row(r), float(r._mapping["sim"])) for r in rows]

    async def set_embeddings(self, user_id, vectors, model):
        from sqlalchemy import text
        await self._init()
        rows = [{"id": i, "u": user_id, "emb": self._vec(v), "m": model} for i, v in vectors.items()
                if len(v) == settings.EMBED_DIM]
        if rows:
            async with self.engine.begin() as conn:
                await conn.execute(text("UPDATE rag_chunks SET embedding = CAST(:emb AS vector), embed_model = :m "
                                        "WHERE id = :id AND user_id = :u"), rows)

    async def delete_material(self, user_id, material_id):
        from sqlalchemy import text
        await self._init()
        async with self.engine.begin() as conn:
            await conn.execute(text("DELETE FROM rag_chunks WHERE user_id = :u AND material_id = :m"),
                               {"u": user_id, "m": material_id})

    async def delete_user(self, user_id):
        from sqlalchemy import text
        await self._init()
        async with self.engine.begin() as conn:
            await conn.execute(text("DELETE FROM rag_chunks WHERE user_id = :u"), {"u": user_id})

    async def count(self, user_id):
        from sqlalchemy import text
        await self._init()
        async with self.engine.connect() as conn:
            return int((await conn.execute(text("SELECT count(*) FROM rag_chunks WHERE user_id = :u"), {"u": user_id})).scalar())


_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = PgVectorStore() if settings.VECTOR_BACKEND == "pgvector" else ChromaVectorStore()
    return _store


def set_vector_store(store: Optional[VectorStore]) -> None:
    """Swap the backend (tests)."""
    global _store
    _store = store
