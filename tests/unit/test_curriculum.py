from types import SimpleNamespace as NS

from app.services.curriculum_service import (
    _budget_skips, build_units, default_skips, fallback_plan, hours_for, validate_plan,
)


def unit(alias, title, hours=1.0, part="Part A", words=1000):
    return {"alias": alias, "section_id": f"s-{alias}", "section_ids": [f"s-{alias}"], "title": title, "part": part,
            "filename": "book.pdf", "hours": hours, "words": words, "summary": "", "page_start": 1, "page_end": 2}


ACTIVE = {u["alias"]: u for u in [unit("U1", "Intro"), unit("U2", "Sets"), unit("U3", "Logic")]}


def plan(*chapters, skip=None):
    return {"specialization": "Maths", "subjects": [{"name": "Foundations", "chapters": list(chapters)}],
            "suggest_skip": skip or []}


def test_valid_plan_passes():
    errors, p = validate_plan(plan({"title": "Basics", "units": ["U1", "U2"], "prerequisites": []},
                                   {"title": "Logic", "units": ["U3"], "prerequisites": ["Basics"]}), ACTIVE, set())
    assert errors == [] and p["subjects"][0]["chapters"][1]["prerequisites"] == ["Basics"]


def test_plan_errors_are_specific():
    errors, p = validate_plan(plan({"title": "A", "units": ["U1", "U9"], "prerequisites": ["B"]},
                                   {"title": "B", "units": ["U1"], "prerequisites": ["A"]}), ACTIVE, set())
    text = " ".join(errors)
    assert p is None
    assert "U9 does not exist" in text and "U1 is used by both" in text
    assert "not assigned" in text and "U2" in text and "U3" in text
    assert "cycle" in text


def test_skipped_units_may_not_be_used():
    errors, _ = validate_plan(plan({"title": "A", "units": ["U1", "U2", "U3"], "prerequisites": []}),
                              {k: v for k, v in ACTIVE.items() if k != "U3"}, {"U3"})
    assert any("U3 is skipped" in e for e in errors)


def test_fallback_uses_every_unit_once_in_reading_order():
    units = [unit(f"U{i}", "Introduction" if i in (1, 5) else f"Topic {i}", hours=0.6, part="P1" if i < 5 else "P2")
             for i in range(1, 9)]
    p = fallback_plan(units, "Goal")
    used = [a for s in p["subjects"] for c in s["chapters"] for a in c["units"]]
    assert used == [u["alias"] for u in units]
    titles = [c["title"] for s in p["subjects"] for c in s["chapters"]]
    assert len(titles) == len(set(titles))  # "Introduction" appears twice but titles stay unique
    errors, _ = validate_plan(p, {u["alias"]: u for u in units}, set())
    assert errors == []


def test_hours_scale_with_words_and_level():
    assert hours_for(6000, "intermediate") == 1.5
    assert hours_for(6000, "beginner") > hours_for(6000, "advanced")


def test_budget_skips_prefer_model_suggestions_then_least_relevant():
    units = [unit("U1", "TCP congestion", 3), unit("U2", "History of telephony", 3), unit("U3", "TCP handshake", 3)]
    assert _budget_skips(units, 6.5, "tcp", []) == ["U2"]
    assert _budget_skips(units, 6.5, "tcp", ["U1"]) == ["U1"]


def test_units_and_default_skips_from_sections():
    m = NS(id="m1", filename="book.pdf")

    def sec(i, title, level, parent=None, words=500):
        return NS(id=f"s{i}", material_id="m1", parent_id=parent, level=level, title=title, page_start=i, page_end=i,
                  word_count=words, summary="", order=i)
    secs = [sec(0, "Preface", 1), sec(1, "Ch 1", 1, words=40), sec(2, "1.1 A", 2, "s1"), sec(3, "1.2 B", 2, "s1"),
            sec(4, "Ch 2", 1, words=0), sec(5, "2.1 C", 2, "s4"), sec(6, "Index", 1, words=20)]
    units = build_units([m], secs, "intermediate")
    # Few top-level sections -> one level down; the chapter intro joins its first unit.
    assert [u["title"] for u in units] == ["Preface", "1.1 A", "1.2 B", "2.1 C", "Index"]
    assert units[1]["section_ids"] == ["s1", "s2"] and units[1]["words"] == 540
    skips = default_skips(units)
    assert set(skips) == {"s0", "s6"}
