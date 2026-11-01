"""Ingestion pipeline: stored upload -> text (+OCR) -> outline + summaries -> section-aware chunks -> vectors.

Runs as a background job (ARQ worker, in-process task, or inline in tests). Every stage writes its
status/progress so the Library can show it, budgets are checked before costly stages, and re-running
is safe: vectors for the material are replaced and sections keep their ids when unchanged, so chapter
links survive a re-index.
"""
import asyncio
import hashlib
import logging
import os
import re
import tempfile
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.rag_store import rag_store
from app.core.request_context import RequestActor, current_actor
from app.models.entities import ChapterSource, MaterialSection, MaterialUpload, User, utcnow
from app.services import extraction, web_source
from app.services.outline_service import Outline, build_outline, estimate_summary_tokens, summarize
from app.services.storage import get_storage
from app.services.storage_quota import StorageQuota
from app.services.usage_service import UsageService

logger = logging.getLogger("studypilot.ingestion")

CHUNK_TARGET, CHUNK_OVERLAP = 900, 150


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> List[str]:
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


def semantic_chunks(text: str, target: int = 900, overlap: int = 150) -> List[str]:
    """Pack whole paragraphs/sentences into ~``target``-char chunks, carrying a short overlap.

    Splitting on sentence boundaries keeps each excerpt self-contained, which improves both
    embedding quality and the citations the tutor shows.
    """
    text = re.sub(r"[ \t]+", " ", text or "").strip()
    if not text:
        return []
    units: List[str] = []
    for para in re.split(r"\n\s*\n", text):
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])", para.strip())
        for s in sentences:
            s = s.strip()
            while len(s) > target:  # very long run-on: hard wrap
                units.append(s[:target]); s = s[target - overlap:]
            if s:
                units.append(s)
    chunks: List[str] = []
    cur: List[str] = []
    for u in units:
        if cur and sum(len(x) + 1 for x in cur) + len(u) > target:
            chunks.append(" ".join(cur))
            carry: List[str] = []  # whole trailing sentences that fit in the overlap budget
            for prev in reversed(cur):
                if sum(len(x) + 1 for x in carry) + len(prev) > overlap:
                    break
                carry.insert(0, prev)
            cur = carry
        cur.append(u)
    if cur:
        chunks.append(" ".join(cur))
    return chunks


# A line that starts a new exam question: "Q3", "Question 3", "3.", "3)", "(3)". Sub-parts like "(a)" stay with
# their question.
QUESTION_START = re.compile(r"^\s*(?:Q(?:uestion)?\s*\.?\s*\d{1,3}\b|\(?\d{1,3}[.)]\s+\S)", re.I | re.M)


def question_chunks(text: str, target: int = CHUNK_TARGET, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Past papers: one chunk per question so a search returns whole questions.

    Falls back to :func:`semantic_chunks` when no question numbering is found, and splits a single very long
    question the same way.
    """
    text = (text or "").strip()
    starts = [m.start() for m in QUESTION_START.finditer(text)]
    if len(starts) < 2:
        return semantic_chunks(text, target, overlap)
    blocks = [text[:starts[0]]] + [text[a:b] for a, b in zip(starts, starts[1:] + [len(text)])]
    out: List[str] = []
    for b in blocks:
        b = re.sub(r"[ \t]+", " ", b).strip()
        if not b:
            continue
        out.extend([b] if len(b) <= 3 * target else semantic_chunks(b, target, overlap))
    return out


class IngestionError(Exception):
    """A failure the learner should see (bad file, over budget); not retried."""


class IngestionPipeline:
    # Jobs outside a request open their own sessions; tests may swap this.
    session_factory = AsyncSessionLocal

    @classmethod
    @asynccontextmanager
    async def _session(cls, db: Optional[AsyncSession]) -> AsyncIterator[AsyncSession]:
        if db is not None:
            yield db
            return
        async with cls.session_factory() as own:
            try:
                yield own
                await own.commit()
            except Exception:
                await own.rollback()
                raise

    @staticmethod
    async def _stage(db: AsyncSession, m: MaterialUpload, status: str, progress: int, own: bool) -> None:
        m.status, m.progress = status, progress
        if own:
            await db.commit()  # make progress visible to pollers
        else:
            await db.flush()

    @classmethod
    async def run(cls, material_id: str, db: Optional[AsyncSession] = None, final_attempt: bool = True) -> str:
        """Process one material. Returns the final status ("ready" or "failed").

        Unexpected errors are re-raised when running in its own session (a worker retries them); on a
        non-final attempt the material stays "pending" with the error noted.
        """
        own = db is None
        async with cls._session(db) as s:
            m = await s.get(MaterialUpload, material_id)
            if not m:
                logger.warning("Ingest: material %s vanished", material_id)
                return "missing"
            user = await s.get(User, m.user_id)
            token = current_actor.set(RequestActor(user_id=m.user_id, feature="materials"))
            try:
                await cls._process(s, m, user, own)
                m.status, m.progress, m.error, m.processed_at = "ready", 100, None, utcnow()
            except (IngestionError, HTTPException, extraction.UnsupportedFile) as e:
                m.status, m.error = "failed", str(getattr(e, "detail", None) or e)[:1000]
            except Exception as e:
                logger.exception("Ingestion failed for %s", material_id)
                retrying = own and not final_attempt
                m.status = "pending" if retrying else "failed"
                m.error = ("Retrying after an error: " if retrying else "Processing error: ") + str(e)[:500]
                if own:
                    await s.commit()
                    raise  # a worker retries transient failures; inline callers just see "failed"
            finally:
                current_actor.reset(token)
            await (s.commit() if own else s.flush())
            return m.status

    @classmethod
    async def _process(cls, db: AsyncSession, m: MaterialUpload, user: User, own: bool) -> None:
        await cls._stage(db, m, "extracting", 5, own)
        if m.source_url:
            ex = await cls._fetch_web(db, m, user, own)
        else:
            async with get_storage().local_copy(m.file_path) as path:
                kind = await asyncio.to_thread(extraction.detect_kind, path, m.filename)
                ex = await asyncio.to_thread(extraction.extract, path, m.filename, kind)
                m.page_count = len(ex.pages)
                await cls._ocr(db, m, user, ex, path, kind, own)
        if not any(p.text.strip() for p in ex.pages):
            raise IngestionError("No readable text found. If this is a scan, OCR could not read it.")

        await cls._stage(db, m, "outlining", 40, own)
        outline = await build_outline(ex, m.filename)
        total_chars = sum(len(p.text) for p in ex.pages)
        await UsageService.check_budget(db, user, estimate_summary_tokens(outline.sections) + total_chars // 4,
                                        "Summarizing and indexing this material")
        await summarize(outline.sections)
        m.outline_source = outline.source
        section_ids = await cls._save_sections(db, m, outline)

        await cls._stage(db, m, "embedding", 60, own)
        chunks = cls._chunks(m, outline, section_ids)
        await rag_store.delete_material(m.user_id, m.id)
        for i in range(0, len(chunks), 200):
            await rag_store.aadd_chunks(m.user_id, chunks[i:i + 200])
            m.progress = 60 + int(35 * min(1.0, (i + 200) / max(1, len(chunks))))
            if own:
                await db.commit()
        m.chunk_count = len(chunks)
        m.embed_model = settings.GEMINI_EMBED_MODEL

    @classmethod
    async def _fetch_web(cls, db: AsyncSession, m: MaterialUpload, user: User, own: bool) -> extraction.Extracted:
        """(Re)fetch a web source as Markdown pages: each web page becomes a top-level section, split into
        pseudo-pages that remember their URL. A snapshot is kept in storage like an uploaded file."""
        try:
            pages = await web_source.collect(m.source_url, include_linked=(m.crawl_pages or 1) > 1,
                                             max_pages=m.crawl_pages or 1)
        except web_source.WebSourceError as e:
            raise IngestionError(str(e))
        ex_pages: List[extraction.Page] = []
        urls: List[str] = []
        for wp in pages:
            for p in extraction.pseudo_pages(web_source.as_section(wp)):
                ex_pages.append(extraction.Page(len(ex_pages) + 1, p.text, p.lines))
                urls.append(wp.url)
        m.page_count = 0  # a refresh replaces this material's pages, so don't count the old ones
        await StorageQuota.check(db, user, len(ex_pages))
        m.page_count, m.page_urls = len(ex_pages), urls
        m.filename = web_source.site_name(pages)
        fd, tmp = tempfile.mkstemp(suffix=".md")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("\n\n".join(p.text for p in ex_pages))
            await get_storage().put(m.file_path, tmp)
        finally:
            os.remove(tmp)
        return extraction.Extracted("markdown", ex_pages)

    @classmethod
    async def _ocr(cls, db, m, user, ex, path, kind, own) -> None:
        scanned = [p for p in ex.pages if p.scanned]
        if not scanned:
            return
        from app.services.llm_client import llm_client
        provider = settings.OCR_PROVIDER
        use_gemini = provider in ("auto", "gemini") and llm_client.is_live
        if provider == "none" or (provider == "gemini" and not use_gemini):
            return
        if use_gemini:
            await UsageService.check_budget(db, user, len(scanned) * settings.OCR_TOKENS_PER_PAGE,
                                            f"Reading {len(scanned)} scanned page(s)")
        for n, page in enumerate(scanned, 1):
            png = await asyncio.to_thread(extraction.page_image_png, path, kind, page.number)
            text = await extraction.ocr_gemini(png) if use_gemini else None
            if text is None:
                text = await asyncio.to_thread(extraction.ocr_tesseract, png)
            if text:
                extraction.apply_ocr_text(page, text)
                m.ocr_pages = (m.ocr_pages or 0) + 1
            m.progress = 5 + int(30 * n / len(scanned))
            if own and n % 5 == 0:
                await db.commit()

    @staticmethod
    async def _save_sections(db: AsyncSession, m: MaterialUpload, outline: Outline) -> List[str]:
        """Replace the material's sections, reusing ids of unchanged ones (same title and start page)."""
        old = (await db.execute(select(MaterialSection).where(MaterialSection.material_id == m.id))).scalars().all()
        reuse = {(o.title, o.page_start): o for o in old}
        ids: List[str] = []
        for sec in outline.sections:
            row = reuse.pop((sec.title, sec.page_start), None)
            if row is None:
                row = MaterialSection(material_id=m.id)
                db.add(row)
            row.level, row.order, row.title = sec.level, sec.index, sec.title
            row.page_start, row.page_end, row.word_count = sec.page_start, sec.page_end, sec.word_count
            row.summary, row.key_concepts = sec.summary, sec.key_concepts
            await db.flush()
            ids.append(row.id)
        for sec, row_id in zip(outline.sections, ids):
            row = await db.get(MaterialSection, row_id)
            row.parent_id = ids[sec.parent] if sec.parent is not None else None
        stale = [o.id for o in reuse.values()]
        if stale:
            await db.execute(delete(ChapterSource).where(ChapterSource.section_id.in_(stale)))
            await db.execute(delete(MaterialSection).where(MaterialSection.id.in_(stale)))
        await db.flush()
        return ids

    @staticmethod
    def _chunks(m: MaterialUpload, outline: Outline, section_ids: List[str]) -> List[Dict[str, Any]]:
        """Chunks never cross a section (or page) boundary, so each cites one section and page."""
        chunks: List[Dict[str, Any]] = []
        split = question_chunks if m.source_type == "past_paper" else semantic_chunks
        for seg in outline.segments:
            for block in split(seg.text, target=CHUNK_TARGET, overlap=CHUNK_OVERLAP):
                n = len(chunks)
                digest = hashlib.sha1(f"{m.id}:{n}:{block}".encode()).hexdigest()[:16]
                chunks.append({
                    "chunk_id": f"{m.id}:{digest}", "text": block, "filename": m.filename,
                    "page_number": seg.page, "chunk_index": n, "material_id": m.id,
                    "section_id": section_ids[seg.section],
                })
        return chunks


async def migrate_legacy_indexes() -> int:
    """Move per-user JSON indexes from before the vector store into it (once; files are renamed)."""
    files = rag_store.legacy_files()
    if not files:
        return 0
    total = 0
    async with AsyncSessionLocal() as db:
        async def material_for(user_id: str, filename: str) -> Optional[str]:
            row = (await db.execute(select(MaterialUpload.id).where(
                MaterialUpload.user_id == user_id, MaterialUpload.filename == filename)
                .order_by(MaterialUpload.created_at.desc()))).scalars().first()
            return row

        for path in files:
            try:
                total += await rag_store.migrate_legacy_file(path, material_for)
            except Exception:
                logger.exception("Legacy index migration failed for %s", path)
    return total
