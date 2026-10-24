"""Flashcard template, normalization, de-duplication and offline fallback."""
from app.services.flashcard_service import BLANK, FlashcardService, cards_from_notes, finalize, generic_cards, normalize_card


def test_cloze_front_hides_the_answer():
    for front in ("Paxos chooses a value once a {{c1::majority quorum}} accepts.",
                  "Paxos chooses a value once a {c1::majority quorum} accepts.",
                  "Paxos chooses a value once a {{c1::majority quorum::hint}} accepts."):
        card = normalize_card({"type": "cloze", "front": front, "back": "majority quorum"})
        assert card["front"] == f"Paxos chooses a value once a {BLANK} accepts."
        assert "majority quorum" not in card["front"] and "majority quorum" in card["back"]


def test_cloze_without_a_deletion_is_rejected_and_qa_with_cloze_marker_becomes_cloze():
    assert normalize_card({"type": "cloze", "front": "No deletion here.", "back": "x"}) is None
    assert normalize_card({"type": "qa", "front": "A {{c1::heap}} gives O(1) min.", "back": "heap"})["type"] == "cloze"


def test_only_the_first_cloze_is_blanked():
    card = normalize_card({"type": "cloze", "front": "{{c1::Raft}} elects a {{c2::leader}} per term.", "back": ""})
    assert card["front"] == f"{BLANK} elects a leader per term."


def test_truefalse_needs_a_verdict_and_is_formatted():
    card = normalize_card({"type": "true_false", "front": "True or False: Raft needs half.", "back": "false - it needs a strict majority"})
    assert card == {"type": "truefalse", "front": "True or false: Raft needs half.", "back": "False. It needs a strict majority"}
    assert normalize_card({"type": "truefalse", "front": "Raft needs half.", "back": "It needs a majority"}) is None


def test_bad_cards_are_rejected():
    assert normalize_card({"type": "qa", "front": "", "back": "x"}) is None
    assert normalize_card({"type": "qa", "front": "What is a quorum (a majority)?", "back": "a majority"}) is None  # leak
    assert normalize_card({"type": "qa", "front": "Same", "back": "same"}) is None
    assert normalize_card({"type": "qa", "front": "Q?" + "x" * 400, "back": "y"}) is None
    assert normalize_card({"type": "qa", "front": "**Why** use `heaps`?", "back": "Fast $min$."}) == \
        {"type": "qa", "front": "Why use heaps?", "back": "Fast min."}


def test_finalize_dedupes_caps_and_cites_uploads():
    drafts = [{"type": "qa", "front": "What is Paxos?", "back": "A consensus protocol.", "source": 1},
              {"type": "qa", "front": "what is paxos", "back": "dup", "source": 0},
              {"type": "qa", "front": "What is Raft?", "back": "An understandable consensus protocol.", "source": 0},
              {"type": "qa", "front": "Already have this?", "back": "Yes it is."},
              {"type": "qa", "front": "What is a term?", "back": "A logical clock period."}]
    cards = finalize(drafts, 2, ["Already have this?"], {1: "paxos.pdf p.3"}, "Chapter notes: Consensus")
    assert [c["front"] for c in cards] == ["What is Paxos?", "What is Raft?"]
    assert cards[0]["source"] == "user_notes" and cards[0]["source_citation"] == "paxos.pdf p.3"
    assert cards[1]["source"] == "ai_generated" and cards[1]["source_citation"] == "Chapter notes: Consensus"
    assert cards[0]["reps"] == 0 and cards[0]["ease"] == 2.5


def test_template_renders_cloze_marker_and_existing_cards():
    prompt = FlashcardService.build_prompt("Heaps", 5, ["[1] From upload: heaps"], "DSA", "beginner", ["Old card?"])
    assert "Write 5 flashcards" in prompt and "{{c1::majority quorum}}" in prompt
    assert "- Old card?" in prompt and "[1] From upload" in prompt and "Learner level: beginner" in prompt


def test_offline_cards_come_from_the_notes():
    notes = """## Definitions
- **Heap**: a complete binary tree where each parent is ordered before its children.
- **Heapify** — turning an array into a heap in O(n) time.

## Key Points
- Inserting into a binary heap costs **O(log n)** because the new item sifts up one level at a time.
"""
    drafts = cards_from_notes("Heaps", notes)
    cards = finalize(drafts, 10, [], {}, "Chapter notes: Heaps")
    assert cards[0]["front"] == "In Heaps, what is Heap?" and cards[0]["back"].startswith("a complete binary tree")
    cloze = next(c for c in cards if c["type"] == "cloze")
    assert BLANK in cloze["front"] and "O(log n)" not in cloze["front"] and "O(log n)" in cloze["back"]


def test_generic_cards_are_valid():
    cards = finalize(generic_cards("Graphs"), 5, [], {}, "Graphs")
    assert len(cards) == 3 and all(BLANK not in c["back"] for c in cards)
    assert any(c["type"] == "cloze" and BLANK in c["front"] for c in cards)


def test_type_mix_survives_truncation():
    drafts = ([{"type": "qa", "front": f"Question {i}?", "back": f"Answer {i}."} for i in range(8)]
              + [{"type": "cloze", "front": f"Fact {i} is {{{{c1::thing{i}}}}}.", "back": ""} for i in range(3)]
              + [{"type": "truefalse", "front": f"Claim {i}.", "back": "True. Because."} for i in range(2)])
    cards = finalize(drafts, 8, [], {}, "x")
    kinds = [c["type"] for c in cards]
    assert len(cards) == 8 and kinds.count("qa") == 5 and kinds.count("cloze") == 2 and kinds.count("truefalse") == 1
