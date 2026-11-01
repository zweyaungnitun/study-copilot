"""Helpers shared by every agent tool.

Every tool returns ``(content, artifact)``: ``content`` is the JSON the model sees and ``artifact``
carries UI-only data (the step summary), so progress text never leaks into the model's context.
"""
import json
from typing import Any, Dict, Tuple

Result = Tuple[str, Dict[str, Any]]


def _out(data: Dict[str, Any], summary: str = "") -> Result:
    return json.dumps(data, ensure_ascii=False, default=str), {"summary": summary}


def _err(message: str) -> Result:
    return _out({"error": message})


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"
