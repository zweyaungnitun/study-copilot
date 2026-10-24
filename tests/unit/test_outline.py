import asyncio
import shutil

import pytest

from app.core.config import settings
from app.services import extraction
from app.services.outline_service import build_outline
from fixtures_pdf import TEXTBOOK, make_scanned, make_textbook


def outline_for(path, name="book.pdf"):
    ex = extraction.extract(path, name)
    return ex, asyncio.run(build_outline(ex, name))


@pytest.fixture
def offline(offline_llm):
    return None


def test_bookmarked_pdf_uses_bookmarks_with_page_ranges(tmp_path, offline):
    answers = make_textbook(str(tmp_path / "b.pdf"), bookmarks=True)
    _, o = outline_for(str(tmp_path / "b.pdf"))
    assert o.source == "bookmarks"
    titles = [s.title for s in o.sections]
    for chapter, sections in TEXTBOOK:
        assert chapter in titles and all(s in titles for s, _ in sections)
    by_title = {s.title: s for s in o.sections}
    for fact, (page, section) in answers.items():
        assert by_title[section].page_start == page == by_title[section].page_end
        assert by_title[section].word_count > 100
    chapter1 = by_title["Chapter 1 The Physical Layer"]
    assert (chapter1.level, chapter1.page_start, chapter1.page_end) == (1, 2, 3)
    assert o.sections[by_title["Signals and Encoding"].parent].title == chapter1.title


def test_headings_detected_from_font_sizes_without_bookmarks(tmp_path, offline):
    make_textbook(str(tmp_path / "h.pdf"), bookmarks=False)
    ex, o = outline_for(str(tmp_path / "h.pdf"))
    assert o.source == "headings"
    levels = {s.title: s.level for s in o.sections}
    assert levels["Chapter 2 The Data Link Layer"] == 1 and levels["Medium Access Control"] == 2
    assert "book.pdf" not in levels  # no stray pseudo-section
    # The running footer is neither a heading nor part of the text.
    assert all("Course Reader" not in g.text for g in o.segments)


def test_markdown_headings_and_code_fences(offline):
    from app.services.extraction import _pseudo_pages, Extracted
    text = "# Algebra\nIntro words here.\n## Linear equations\nSolve for x.\n```\n# not a heading\n```\n## Quadratics\nUse the formula."
    o = asyncio.run(build_outline(Extracted("markdown", _pseudo_pages(text)), "notes.md"))
    assert o.source == "markdown"
    assert [(s.title, s.level) for s in o.sections] == [("Algebra", 1), ("Linear equations", 2), ("Quadratics", 2)]


def test_outline_without_structure_falls_back_to_page_windows(offline):
    from app.services.extraction import Extracted, Page
    pages = [Page(i, f"Plain text on page {i} without headings at all.") for i in range(1, 26)]
    o = asyncio.run(build_outline(Extracted("pdf", pages), "scan.pdf"))
    assert o.source == "pages"
    assert [s.title for s in o.sections] == ["Pages 1-10", "Pages 11-20", "Pages 21-25"]


def test_outline_is_capped(monkeypatch, offline):
    from app.services.extraction import _pseudo_pages, Extracted
    monkeypatch.setattr(settings, "MAX_OUTLINE_SECTIONS", 5)
    text = "\n".join(f"# Part {i}\ntext {i}\n## Detail {i}a\nmore\n## Detail {i}b\nmore" for i in range(4))
    o = asyncio.run(build_outline(Extracted("markdown", _pseudo_pages(text)), "n.md"))
    assert len(o.sections) == 4 and all(s.level == 1 for s in o.sections)
    assert sum(s.word_count for s in o.sections) == sum(len(g.text.split()) for g in o.segments)


def test_scanned_page_is_flagged_and_ocr_reads_it(tmp_path):
    make_scanned(str(tmp_path / "s.pdf"))
    ex = extraction.extract(str(tmp_path / "s.pdf"), "s.pdf")
    assert [p.scanned for p in ex.pages] == [True]
    if not shutil.which("tesseract"):
        pytest.skip("tesseract not installed")
    text = extraction.ocr_tesseract(extraction.page_image_png(str(tmp_path / "s.pdf"), "pdf", 1))
    assert "Photosynthesis" in text


def test_detect_kind_rejects_unsupported(tmp_path):
    exe = tmp_path / "x.pdf"
    exe.write_bytes(b"MZ\x90\x00" + b"\x00" * 200)  # Windows executable renamed to .pdf
    with pytest.raises(extraction.UnsupportedFile):
        extraction.detect_kind(str(exe), "x.pdf")
    doc = tmp_path / "notes.docx"
    doc.write_bytes(b"PK\x03\x04" + b"\x00" * 200)
    with pytest.raises(extraction.UnsupportedFile):
        extraction.detect_kind(str(doc), "notes.docx")
    nb = tmp_path / "lab.ipynb"
    nb.write_text('{"cells": [{"cell_type": "markdown", "source": ["# Lab 1\\n", "Intro"]}, {"cell_type": "code", "source": "print(1)"}]}')
    assert extraction.detect_kind(str(nb), "lab.ipynb") == "notebook"
    pages = extraction.extract(str(nb), "lab.ipynb").pages
    assert "# Lab 1" in pages[0].text and "```\nprint(1)\n```" in pages[0].text
