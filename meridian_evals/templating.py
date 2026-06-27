"""Tiny ``{{ path }}`` templating so expected values are resolved from the live
/api/state oracle at run time instead of being hard-coded.

The pinned profile can shift within a session (e.g. receiving salary moves the
balance from €2,668.83 to €5,168.83), so datasets reference the oracle:

    must_contain: ["{{ accounts.0.balance_cents | euros }}"]
    expected_answer: "Your balance is {{ accounts.0.balance_cents | euros }}."

Supported filters: ``euros`` (cents int -> "€5,168.83"), ``cents`` (raw).
"""

from __future__ import annotations

import re
from typing import Any

_TOKEN = re.compile(r"\{\{\s*([^}|]+?)\s*(?:\|\s*([a-z_]+)\s*)?\}\}")


def _resolve(state: dict[str, Any], path: str) -> Any:
    cur: Any = state
    for part in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def _apply_filter(value: Any, filt: str | None) -> str:
    if value is None:
        return ""
    if filt == "euros":
        try:
            return f"€{int(value) / 100:,.2f}"
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def render(text: str, state: dict[str, Any]) -> str:
    def repl(m: re.Match[str]) -> str:
        return _apply_filter(_resolve(state, m.group(1)), m.group(2))

    return _TOKEN.sub(repl, text)


def render_expected(expected: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Deep-render strings (and lists of strings) in an expected block."""
    out: dict[str, Any] = {}
    for k, v in expected.items():
        if isinstance(v, str):
            out[k] = render(v, state)
        elif isinstance(v, list):
            out[k] = [render(x, state) if isinstance(x, str) else x for x in v]
        else:
            out[k] = v
    return out
