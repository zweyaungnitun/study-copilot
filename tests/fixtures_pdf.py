"""Build small but realistic PDFs for ingestion tests (reportlab), with known structure and facts.

TEXTBOOK lists (chapter, [(section, fact)]): every section gets its own page whose text contains its
fact, so retrieval tests know exactly which page and section should answer each question.
"""
from typing import List, Tuple

TEXTBOOK: List[Tuple[str, List[Tuple[str, str]]]] = [
    ("Chapter 1 The Physical Layer", [
        ("Signals and Encoding", "Manchester encoding guarantees a voltage transition in the middle of every bit period, which keeps sender and receiver clocks synchronized."),
        ("Transmission Media", "Single-mode optical fiber carries one light path and reaches tens of kilometres without repeaters, while multimode fiber suits short runs inside buildings."),
    ]),
    ("Chapter 2 The Data Link Layer", [
        ("Framing and Error Detection", "A cyclic redundancy check appends remainder bits from polynomial division so the receiver detects burst errors in a frame."),
        ("Medium Access Control", "Ethernet uses CSMA/CD: a station listens before sending and, after a collision, waits a random binary exponential backoff."),
    ]),
    ("Chapter 3 The Network Layer", [
        ("IPv4 Addressing", "Subnetting borrows host bits to create smaller networks; a /26 prefix leaves six host bits for sixty-two usable addresses."),
        ("Routing Algorithms", "Dijkstra's shortest path algorithm underpins link-state routing protocols such as OSPF, which flood link-state advertisements."),
    ]),
    ("Chapter 4 The Transport Layer", [
        ("TCP Reliability", "TCP performs a three-way handshake of SYN, SYN-ACK and ACK before any application data is exchanged."),
        ("Congestion Control", "During slow start the TCP congestion window doubles every round-trip time until it reaches the slow start threshold."),
    ]),
]

FILLER = (
    "Students should read this section slowly, take notes in their own words, and attempt the review questions "
    "at the end of the chapter before moving on. Worked examples in the lecture slides follow the same order as "
    "this text and use the same terminology. "
)


def _wrap(c, text: str, x: float, y: float, width: int = 95, leading: int = 14) -> float:
    import textwrap
    for line in textwrap.wrap(text, width):
        c.drawString(x, y, line)
        y -= leading
    return y


def make_textbook(path: str, bookmarks: bool = True, front_and_back: bool = True) -> dict:
    """Write the textbook PDF. Returns {fact: (page, section title)} for the golden questions."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(path, pagesize=A4)
    _, h = A4
    page = 0
    answers = {}

    def new_page():
        nonlocal page
        if page:
            c.showPage()
        page += 1
        c.setFont("Helvetica", 9)
        c.drawString(72, 30, "Computer Networks - Course Reader")  # running footer on every page

    if front_and_back:
        new_page()
        c.setFont("Helvetica", 10)
        y = h - 90
        c.setFont("Helvetica-Bold", 20)
        c.drawString(72, y, "Preface")
        c.setFont("Helvetica", 10)
        _wrap(c, "This course reader accompanies the networking module. " + FILLER * 3, 72, y - 30)
        if bookmarks:
            c.bookmarkPage("preface")
            c.addOutlineEntry("Preface", "preface", level=0)

    for ci, (chapter, sections) in enumerate(TEXTBOOK):
        for si, (section, fact) in enumerate(sections):
            new_page()
            y = h - 90
            if si == 0:
                c.setFont("Helvetica-Bold", 20)
                c.drawString(72, y, chapter)
                if bookmarks:
                    c.bookmarkPage(f"c{ci}")
                    c.addOutlineEntry(chapter, f"c{ci}", level=0)
                y -= 36
            c.setFont("Helvetica-Bold", 14)
            c.drawString(72, y, section)
            if bookmarks:
                c.bookmarkPage(f"c{ci}s{si}")
                c.addOutlineEntry(section, f"c{ci}s{si}", level=1)
            c.setFont("Helvetica", 10)
            y = _wrap(c, FILLER + fact + " " + FILLER * 2, 72, y - 24)
            answers[fact] = (page, section)

    if front_and_back:
        new_page()
        c.setFont("Helvetica-Bold", 20)
        c.drawString(72, h - 90, "Index")
        c.setFont("Helvetica", 10)
        _wrap(c, "backoff 4, CRC 3, fiber 2, handshake 7, Manchester 1, OSPF 6, slow start 8, subnetting 5. " * 3, 72, h - 120)
        if bookmarks:
            c.bookmarkPage("index")
            c.addOutlineEntry("Index", "index", level=0)
    c.save()
    return answers


def make_scanned(path: str, text: str = "Photosynthesis converts light energy into chemical energy stored in glucose.") -> None:
    """One page that is only an image of text (no text layer), like a phone scan of a notebook."""
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    img = Image.new("RGB", (1700, 600), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 44)
    except OSError:
        font = ImageFont.load_default()
    import textwrap
    y = 60
    for line in ["Biology Notes"] + textwrap.wrap(text, 55):
        draw.text((60, y), line, fill="black", font=font)
        y += 70
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    c.drawImage(ImageReader(img), 36, h - 300, width=w - 72, height=(w - 72) * 600 / 1700)
    c.save()
