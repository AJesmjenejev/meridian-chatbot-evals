"""Record/replay ("cassette") support so the suite runs offline.

* ``RecordingClient`` wraps the live client and saves every chat / llm / ui-event
  / state / catalogue response to a JSON cassette (flushed after each call, so a
  partial cassette survives the token expiring mid-run).
* ``MockClient`` replays a cassette with **no network** — same interface as
  ``MeridianClient``, so the runner and scorers are unchanged.

Replay fidelity: a cassette recorded with ``--record`` replays the real chat
replies AND the real LLM-judge verdicts, so ``--mock`` reproduces the exact
scored run offline. Chat replies are stored as a list per message and cycled, so
recorded run-to-run variance is preserved across reps.
"""

from __future__ import annotations

import json
from typing import Any

from .models import ChatReply

_REPLY_FIELDS = ("text", "thread_id", "turn", "tool_rounds", "latency_ms", "error", "raw_events")


def _reply_to_dict(r: ChatReply) -> dict[str, Any]:
    return {k: getattr(r, k) for k in _REPLY_FIELDS}


_REPLY_DEFAULTS = {
    "text": "",
    "thread_id": None,
    "turn": None,
    "tool_rounds": 0,
    "latency_ms": 0.0,
    "error": None,
    "raw_events": None,
}


def _dict_to_reply(d: dict[str, Any]) -> ChatReply:
    # Use dataclass-friendly defaults so a hand-edited cassette missing a field
    # (e.g. latency_ms) doesn't become None and crash reporting/scoring.
    kw = {}
    for k in _REPLY_FIELDS:
        v = d.get(k, _REPLY_DEFAULTS[k])
        kw[k] = v if v is not None else _REPLY_DEFAULTS[k]
    if kw["raw_events"] is None:
        kw["raw_events"] = []
    return ChatReply(**kw)


def _llm_key(user: str, system: str | None) -> str:
    return json.dumps([system or "", user], ensure_ascii=False)


def _ui_key(kind: str, payload: dict | None) -> str:
    return f"{kind}|{json.dumps(payload or {}, sort_keys=True, ensure_ascii=False)}"


class _Cassette:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {
            "chat": {},
            "llm": {},
            "ui_event": {},
            "state": None,
            "catalogue": {},
        }

    @classmethod
    def load(cls, path: str) -> _Cassette:
        c = cls()
        with open(path, encoding="utf-8") as fh:
            c.data = json.load(fh)
        for key in ("chat", "llm", "ui_event", "catalogue"):
            c.data.setdefault(key, {})
        return c

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=1, ensure_ascii=False, default=str)


class RecordingClient:
    """Delegates to a real client and records every response to a cassette."""

    def __init__(self, real: Any, path: str) -> None:
        self._real = real
        self._path = path
        self._cass = _Cassette()
        self.session_id: str | None = None

    def redeem(self) -> str:
        self.session_id = self._real.redeem()
        return self.session_id

    def get_state(self, *, refresh: bool = False) -> dict[str, Any]:
        st = self._real.get_state(refresh=refresh)
        self._cass.data["state"] = st
        self._flush()
        return st

    def catalogue(self, name: str) -> Any:
        v = self._real.catalogue(name)
        self._cass.data["catalogue"][name] = v
        self._flush()
        return v

    def chat(self, message: str, thread_id: str | None = None) -> ChatReply:
        r = self._real.chat(message, thread_id=thread_id)
        self._cass.data["chat"].setdefault(message, []).append(_reply_to_dict(r))
        self._flush()
        return r

    def llm(self, user: str, system: str | None = None) -> dict[str, Any]:
        resp = self._real.llm(user=user, system=system)
        self._cass.data["llm"][_llm_key(user, system)] = resp
        self._flush()
        return resp

    def ui_event(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = self._real.ui_event(kind, payload)
        self._cass.data["ui_event"][_ui_key(kind, payload)] = resp
        self._flush()
        return resp

    def _flush(self) -> None:
        self._cass.save(self._path)


class MockClient:
    """Replays a cassette with no network. Same interface as MeridianClient."""

    def __init__(self, path: str, **_ignored: Any) -> None:
        self._cass = _Cassette.load(path)
        self._chat_idx: dict[str, int] = {}
        self.session_id = "mock-session"

    def redeem(self) -> str:
        return self.session_id

    def get_state(self, *, refresh: bool = False) -> dict[str, Any]:
        st = self._cass.data.get("state")
        if st is None:
            raise RuntimeError("cassette has no recorded /api/state")
        return st

    def catalogue(self, name: str) -> Any:
        return self._cass.data["catalogue"].get(name)

    def chat(self, message: str, thread_id: str | None = None) -> ChatReply:
        lst = self._cass.data["chat"].get(message)
        if not lst:
            return ChatReply(text="", error=f"no recorded reply for: {message!r}")
        i = self._chat_idx.get(message, 0)
        self._chat_idx[message] = i + 1
        return _dict_to_reply(lst[i % len(lst)])

    def llm(self, user: str, system: str | None = None) -> dict[str, Any]:
        resp = self._cass.data["llm"].get(_llm_key(user, system))
        if resp is None:
            # No recorded judge verdict -> let the judge scorer score as not-applicable.
            raise RuntimeError("no recorded /api/llm response in cassette")
        return resp

    def ui_event(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = self._cass.data["ui_event"].get(_ui_key(kind, payload))
        if resp is None:
            return {"ok": True, "state": self._cass.data.get("state")}
        return resp
