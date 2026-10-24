"""Curriculum from the learner's own materials.

The outline (not retrieval) drives this: sections become study *units*, the LLM groups units into
subjects/chapters by id only, and the result is validated in code (ids exist, every unit used once or
explicitly skipped, prerequisites acyclic). Hours come from word counts, never from the model.
"""
import graphlib
import json
import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import MaterialSection, MaterialUpload
from app.services.llm_client import llm_client
from app.services.rag_service import UNTRUSTED_NOTICE

logger = logging.getLogger("studypilot.curriculum")

# Careful-reading pace (words/hour) by level; x PRACTICE_MULTIPLIER for notes, exercises and review.
READING_WPH = {"beginner": 4500, "intermediate": 6000, "advanced": 7500}
PRACTICE_MULTIPLIER = 1.5
MAX_UNITS = 150
SKIP_TITLES = re.compile(
    r"^\s*(front matter|preface|foreword|acknowledg|dedication|about the author|contents|table of contents|"
    r"copyright|index\b|bibliograph|references\b|further reading|appendix|glossary|list of (figures|tables))", re.I)


def hours_for(words: int, level: str) -> float:
    pace = READING_WPH.get((level or "").lower(), READING_WPH["intermediate"])
    return round(words / pace * PRACTICE_MULTIPLIER, 2)


def round_hours(h: float) -> float:
    return max(0.5, round(h * 2) / 2)


# ---------------------------------------------------------------------------- units
async def load_sections(db: AsyncSession, user_id: str, material_ids: Sequence[str]) -> Tuple[List[MaterialUpload], List[MaterialSection]]:
    mats = (await db.execute(select(MaterialUpload).where(
        MaterialUpload.id.in_(list(material_ids)), MaterialUpload.user_id == user_id))).scalars().all()
    order = {mid: i for i, mid in enumerate(material_ids)}
    mats = sorted(mats, key=lambda m: order.get(m.id, 0))
    secs = (await db.execute(select(MaterialSection).where(MaterialSection.material_id.in_([m.id for m in mats]))
                             .order_by(MaterialSection.order))).scalars().all()
    by_mat = {m.id: i for i, m in enumerate(mats)}
    return mats, sorted(secs, key=lambda s: (by_mat[s.material_id], s.order))


def build_units(mats: List[MaterialUpload], sections: List[MaterialSection], level: str) -> List[Dict[str, Any]]:
    """Pick a granularity per material (top-level sections, or one level down for short outlines)."""
    names = {m.id: m.filename for m in mats}
    children: Dict[str, List[MaterialSection]] = defaultdict(list)
    for s in sections:
        if s.parent_id:
            children[s.parent_id].append(s)

    def subtree(s: MaterialSection) -> List[MaterialSection]:
        out = [s]
        for c in children.get(s.id, []):
            out.extend(subtree(c))
        return out

    units: List[Dict[str, Any]] = []
    for m in mats:
        secs = [s for s in sections if s.material_id == m.id]
        if not secs:
            continue
        top = min(s.level for s in secs)
        tops = [s for s in secs if s.level == top and not SKIP_TITLES.match(s.title)]
        deeper = [s for s in secs if s.level == top + 1]
        unit_level = top + 1 if len(tops) < 6 and deeper and len(deeper) <= MAX_UNITS else top
        parent_intro: Dict[str, MaterialSection] = {}
        for s in secs:
            if s.level > unit_level:
                continue
            has_unit_children = any(c.level == unit_level for c in children.get(s.id, []))
            if s.level < unit_level and has_unit_children:
                if s.word_count:
                    parent_intro[s.id] = s  # its own intro text joins its first unit
                continue
            covered = subtree(s)
            intro = parent_intro.pop(s.parent_id, None) if s.parent_id else None
            if intro:
                covered = [intro] + covered
            words = sum(x.word_count or 0 for x in covered)
            parent = next((p for p in secs if p.id == s.parent_id), None)
            units.append({
                "alias": f"U{len(units) + 1}", "section_id": s.id, "section_ids": [x.id for x in covered],
                "material_id": m.id, "filename": names[m.id], "title": s.title, "part": parent.title if parent else "",
                "page_start": min(x.page_start for x in covered), "page_end": max(x.page_end for x in covered),
                "words": words, "hours": hours_for(words, level), "summary": s.summary or "",
            })
    return units[:MAX_UNITS]


def default_skips(units: List[Dict[str, Any]]) -> Dict[str, str]:
    """section_id -> reason, for front/back matter and near-empty sections."""
    out = {}
    for u in units:
        if SKIP_TITLES.match(u["title"]):
            out[u["section_id"]] = "Front or back matter"
        elif u["words"] < 30:
            out[u["section_id"]] = "Almost no text"
    return out


# ---------------------------------------------------------------------------- validation
def validate_plan(plan: Any, active: Dict[str, Dict[str, Any]], skipped_aliases: set) -> Tuple[List[str], Optional[Dict[str, Any]]]:
    """Check an LLM grouping against the units. Returns (errors, normalized plan)."""
    errors: List[str] = []
    if not isinstance(plan, dict) or not isinstance(plan.get("subjects"), list) or not plan["subjects"]:
        return ["Return an object with a non-empty \"subjects\" list."], None
    used: Dict[str, str] = {}
    titles: set = set()
    subjects = []
    for s in plan["subjects"]:
        if not isinstance(s, dict):
            continue
        chapters = []
        for c in s.get("chapters") or []:
            if not isinstance(c, dict):
                continue
            title = str(c.get("title", "")).strip()[:200]
            aliases = [str(a).strip() for a in (c.get("units") or [])]
            if not title:
                errors.append("Every chapter needs a title.")
                continue
            if title in titles:
                errors.append(f'Chapter title "{title}" is used twice; titles must be unique.')
            titles.add(title)
            if not aliases:
                errors.append(f'Chapter "{title}" has no units.')
            for a in aliases:
                if a in skipped_aliases:
                    errors.append(f"{a} is skipped and must not be used.")
                elif a not in active:
                    errors.append(f"{a} does not exist.")
                elif a in used:
                    errors.append(f'{a} is used by both "{used[a]}" and "{title}".')
                else:
                    used[a] = title
            prereqs = [str(p).strip() for p in (c.get("prerequisites") or []) if str(p).strip()]
            chapters.append({"title": title, "units": aliases, "prerequisites": prereqs})
        if chapters:
            subjects.append({"name": str(s.get("name") or f"Part {len(subjects) + 1}").strip()[:200], "chapters": chapters})
    missing = [a for a in active if a not in used]
    if missing:
        errors.append(f"These units are not assigned to any chapter: {', '.join(missing)}.")
    all_titles = {c["title"] for s in subjects for c in s["chapters"]}
    graph = {}
    for s in subjects:
        for c in s["chapters"]:
            bad = [p for p in c["prerequisites"] if p not in all_titles or p == c["title"]]
            if bad:
                errors.append(f'Chapter "{c["title"]}" lists unknown prerequisites: {", ".join(bad)}.')
            graph[c["title"]] = {p for p in c["prerequisites"] if p in all_titles and p != c["title"]}
    try:
        tuple(graphlib.TopologicalSorter(graph).static_order())
    except graphlib.CycleError as e:
        errors.append(f"Prerequisites form a cycle: {' -> '.join(e.args[1])}.")
    if errors:
        return errors, None
    return [], {"specialization": str(plan.get("specialization") or "").strip()[:200], "subjects": subjects,
                "suggest_skip": [a for a in plan.get("suggest_skip") or [] if a in active]}


def fallback_plan(units: List[Dict[str, Any]], goal: str) -> Dict[str, Any]:
    """Reading order: one subject per part (or per ~6 chapters), small units merged up to ~1-3 hours."""
    groups: List[Tuple[str, List[Dict[str, Any]]]] = []
    for u in units:
        key = u["part"] or u["filename"]
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(u)
    subjects = []
    prev_title: Optional[str] = None
    seen: set = set()
    for name, members in groups:
        chapters: List[List[Dict[str, Any]]] = []
        cur: List[Dict[str, Any]] = []
        for u in members:
            if cur and (sum(x["hours"] for x in cur) >= 1.0 or sum(x["hours"] for x in cur) + u["hours"] > 3.0):
                chapters.append(cur)
                cur = []
            cur.append(u)
        if cur:
            chapters.append(cur)
        for i in range(0, len(chapters), 6):
            subj = {"name": name if len(chapters) <= 6 else f"{name} ({i // 6 + 1})", "chapters": []}
            for grp in chapters[i:i + 6]:
                base = grp[0]["title"] if len(grp) == 1 else f"{grp[0]['title']} – {grp[-1]['title']}"
                title, n = base[:200], 1
                while title in seen:  # e.g. two books that both start with "Introduction"
                    n += 1
                    title = f"{base[:190]} ({n})"
                seen.add(title)
                subj["chapters"].append({"title": title, "units": [u["alias"] for u in grp],
                                         "prerequisites": [prev_title] if prev_title else []})
                prev_title = title
            subjects.append(subj)
    return {"specialization": goal, "subjects": subjects, "suggest_skip": []}


# ---------------------------------------------------------------------------- planning
def _prompt(units: List[Dict[str, Any]], goal: str, level: str, budget: float, total: float,
            preferences: Optional[str]) -> str:
    rows = "\n".join(
        f'<material id="{u["alias"]}" file="{u["filename"]}" part="{u["part"][:80]}" pages="{u["page_start"]}-{u["page_end"]}" '
        f'hours="{u["hours"]:.1f}">{u["title"][:150]} :: {u["summary"][:220]}</material>' for u in units)
    over = (f"\nThe units need about {total:.0f} h but the budget is {budget:.0f} h: list in \"suggest_skip\" the "
            "units least important for the goal so the rest fits. Still assign EVERY unit to a chapter." if total > budget else "")
    return f"""Design a study curriculum from the learner's own material.
Goal: {goal}
Level: {level}
Time budget: {budget:.0f} hours
Learner's wishes: {preferences or 'none'}

Units of study, in reading order:
{UNTRUSTED_NOTICE}
{rows}

Rules:
- Group units into 2-8 subjects, each with chapters. A chapter is 1-4 consecutive or closely related units (aim for 1-4 hours).
- Use every unit id exactly once. Do not invent ids. Keep the books' order unless a dependency requires otherwise.
- Chapter titles: short, specific and unique. Subject names describe the theme.
- prerequisites: EXACT titles of earlier chapters that must come first (no cycles).{over}

Return JSON: {{"specialization": string, "subjects": [{{"name": string, "chapters": [{{"title": string, "units": ["U1", ...], "prerequisites": [string]}}]}}], "suggest_skip": ["U.."]}}"""


def _relevance(u: Dict[str, Any], goal: str) -> float:
    g = {w for w in re.findall(r"[a-z0-9]{3,}", goal.lower())}  # 3+ so acronyms like TCP count
    t = set(re.findall(r"[a-z0-9]{3,}", f"{u['title']} {u['summary']}".lower()))
    return len(g & t) / (len(g) or 1)


def _budget_skips(units: List[Dict[str, Any]], budget: float, goal: str, preferred: Sequence[str]) -> List[str]:
    """Aliases to drop until the plan fits: the model's suggestions first, then least goal-relevant, latest first."""
    total = sum(u["hours"] for u in units)
    by_alias = {u["alias"]: u for u in units}
    order = [by_alias[a] for a in preferred if a in by_alias]
    order += sorted((u for u in units if u["alias"] not in preferred), key=lambda u: (_relevance(u, goal), -int(u["alias"][1:])))
    out = []
    for u in order:
        if total <= budget:
            break
        out.append(u["alias"])
        total -= u["hours"]
    return out


async def propose(
    db: AsyncSession,
    user_id: str,
    material_ids: Sequence[str],
    goal: str,
    level: str,
    budget_hours: float,
    skip_section_ids: Optional[Sequence[str]] = None,
    preferences: Optional[str] = None,
) -> Dict[str, Any]:
    mats, sections = await load_sections(db, user_id, material_ids)
    not_ready = [m.filename for m in mats if m.status not in ("ready", "processed")]
    if len(mats) != len(set(material_ids)):
        raise ValueError("Some materials were not found in your library.")
    if not_ready:
        raise ValueError(f"Still processing: {', '.join(not_ready)}. Try again when they are ready.")
    units = build_units(mats, sections, level)
    if not units:
        raise ValueError("These materials have no outline yet. Re-index them and try again.")

    defaults = default_skips(units)
    if skip_section_ids is None:
        skipped_ids = dict(defaults)
    else:
        skipped_ids = {sid: defaults.get(sid, "Skipped by you") for sid in skip_section_ids}
    skipped_aliases = {u["alias"] for u in units if u["section_id"] in skipped_ids}
    active = {u["alias"]: u for u in units if u["alias"] not in skipped_aliases}
    if not active:
        raise ValueError("Every section is skipped. Keep at least one.")
    total = sum(u["hours"] for u in active.values())

    plan, method = None, "fallback"
    if llm_client.is_live:
        prompt = _prompt(list(active.values()), goal, level, budget_hours, total, preferences)
        for attempt in range(2):
            raw = await llm_client.generate_json(prompt, max_tokens=8192, fallback={})
            errors, plan = validate_plan(raw, active, skipped_aliases)
            if plan:
                method = "llm"
                break
            logger.warning("Curriculum plan invalid (attempt %d): %s", attempt + 1, errors[:5])
            prompt += "\n\nYour previous answer was invalid:\n- " + "\n- ".join(errors[:12]) + \
                      f"\nPrevious answer: {json.dumps(raw)[:3000]}\nReturn a corrected JSON object."
    if not plan:
        plan = fallback_plan(list(active.values()), goal)

    suggest = _budget_skips(list(active.values()), budget_hours, goal, plan.get("suggest_skip") or []) if total > budget_hours else []
    subjects = []
    for s in plan["subjects"]:
        chapters = []
        for c in s["chapters"]:
            members = [active[a] for a in c["units"]]
            chapters.append({
                "title": c["title"],
                "estimated_hours": round_hours(sum(u["hours"] for u in members)),
                "prerequisites": c["prerequisites"],
                "source_section_ids": [sid for u in members for sid in u["section_ids"]],
                "sources": [{"section_id": u["section_id"], "title": u["title"], "filename": u["filename"],
                             "page_start": u["page_start"], "page_end": u["page_end"], "hours": round(u["hours"], 1)}
                            for u in members],
            })
        subjects.append({"name": s["name"], "chapters": chapters})

    unit_by_alias = {u["alias"]: u for u in units}
    planned_hours = sum(c["estimated_hours"] for s in subjects for c in s["chapters"])
    return {
        "proposal": {"specialization": plan.get("specialization") or goal, "subjects": subjects},
        "method": method,
        "total_hours": round(planned_hours, 1),
        "budget_hours": round(budget_hours, 1),
        "over_budget": planned_hours > budget_hours,
        "skipped": [{"section_id": u["section_id"], "title": u["title"], "filename": u["filename"],
                     "reason": skipped_ids[u["section_id"]], "hours": round(u["hours"], 1)}
                    for u in units if u["section_id"] in skipped_ids],
        "suggested_skips": [{"section_id": unit_by_alias[a]["section_id"], "title": unit_by_alias[a]["title"],
                             "filename": unit_by_alias[a]["filename"], "hours": round(unit_by_alias[a]["hours"], 1)}
                            for a in suggest],
        "units": [{"section_id": u["section_id"], "title": u["title"], "filename": u["filename"], "part": u["part"],
                   "page_start": u["page_start"], "page_end": u["page_end"], "hours": round(u["hours"], 1),
                   "skipped": u["section_id"] in skipped_ids} for u in units],
    }
