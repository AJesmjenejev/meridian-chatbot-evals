"""HTTP client for the Meridian banking prototype API.

Endpoints (discovered from the app's own app.js):
    POST /api/redeem    {token}                          -> {ok, sessionId}
    GET  /api/state     ?session=SID                     -> {state}
    POST /api/chat      {sessionId, message, threadId}   -> SSE stream
    POST /api/llm       {sessionId, user, system?}       -> {ok, text, latency_ms}
    POST /api/ui-event  {sessionId, kind, payload}       -> {state}
    GET  /api/catalogues/{name} ?session=SID             -> catalogue json

Notes
-----
* /api/chat returns Server-Sent Events. Frames: ``tool_round`` {round},
  ``chunk`` {text}, ``done`` {turn, threadId}, ``error`` {candidate_visible}.
* /api/llm is scope-guarded to banking topics, so judge prompts must be framed
  as banking QA grading (they are, in scorers/llm_judge.py).
* If the live GET /api/state is unavailable (e.g. a network that blocks it, or
  CI), the client falls back to a captured ``state_file`` so the harness still
  runs offline.
"""

from __future__ import annotations

import json
import time
from typing import Any

import requests

from .models import ChatReply


class MeridianClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        state_file: str | None = None,
        timeout: int = 60,
        verify_ssl: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.state_file = state_file
        self.session_id: str | None = None
        self._http = requests.Session()
        # Escape hatch for networks whose TLS root CA isn't in certifi.
        # Default stays secure.
        self._http.verify = verify_ssl
        if not verify_ssl:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self._state_cache: dict[str, Any] | None = None

    # ------------------------------------------------------------------ auth
    def redeem(self) -> str:
        r = self._http.post(
            f"{self.base_url}/api/redeem",
            json={"token": self.token},
            timeout=self.timeout,
        )
        r.raise_for_status()
        body = r.json()
        if not body.get("sessionId"):
            raise RuntimeError(f"redeem returned no sessionId: {body}")
        self.session_id = body["sessionId"]
        return self.session_id

    def _require_session(self) -> str:
        if not self.session_id:
            self.redeem()
        assert self.session_id
        return self.session_id

    # ----------------------------------------------------------------- state
    def get_state(self, *, refresh: bool = False) -> dict[str, Any]:
        """Return the account/card/transaction state (ground-truth oracle).

        Tries the live GET first; on any failure falls back to ``state_file``.
        """
        if self._state_cache is not None and not refresh:
            return self._state_cache
        sid = self._require_session()
        try:
            r = self._http.get(
                f"{self.base_url}/api/state",
                params={"session": sid},
                headers={"Accept": "application/json"},
                timeout=self.timeout,
                allow_redirects=False,
            )
            if r.status_code == 200 and r.headers.get("content-type", "").startswith(
                "application/json"
            ):
                self._state_cache = r.json().get("state", r.json())
                return self._state_cache
            raise RuntimeError(f"state http {r.status_code}")
        except Exception as exc:  # noqa: BLE001 - intentional fallback
            if self.state_file:
                with open(self.state_file, encoding="utf-8") as fh:
                    data = json.load(fh)
                self._state_cache = data.get("state", data)
                return self._state_cache
            raise RuntimeError(
                f"GET /api/state failed ({exc}); set MERIDIAN_STATE_FILE to a "
                "captured state.json to run where the GET is unavailable."
            ) from exc

    def catalogue(self, name: str) -> Any:
        sid = self._require_session()
        r = self._http.get(
            f"{self.base_url}/api/catalogues/{name}",
            params={"session": sid},
            timeout=self.timeout,
            allow_redirects=False,
        )
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------ chat
    def chat(self, message: str, thread_id: str | None = None) -> ChatReply:
        sid = self._require_session()
        start = time.perf_counter()
        reply = ChatReply(text="", thread_id=thread_id)
        try:
            r = self._http.post(
                f"{self.base_url}/api/chat",
                json={"sessionId": sid, "message": message, "threadId": thread_id},
                headers={"Accept": "text/event-stream"},
                timeout=self.timeout,
                stream=True,
            )
            r.encoding = "utf-8"  # SSE body is UTF-8 (€ etc.); avoid latin-1 mojibake
            ct = r.headers.get("content-type", "")
            if "text/event-stream" not in ct:
                body = r.json() if "application/json" in ct else {"error": r.text[:200]}
                reply.error = body.get("error", f"chat http {r.status_code}")
                return reply
            text_parts: list[str] = []
            for event, data in _iter_sse(r):
                reply.raw_events.append({"event": event, "data": data})
                if event == "tool_round":
                    reply.tool_rounds += 1
                elif event == "chunk":
                    text_parts.append(data.get("text", ""))
                elif event == "done":
                    reply.thread_id = data.get("threadId", reply.thread_id)
                    reply.turn = data.get("turn")
                elif event == "error":
                    reply.error = data.get("candidate_visible", "interrupted")
            reply.text = "".join(text_parts).strip()
            # If the answer streamed before a trailing stream error, keep the
            # answer (the error event is recorded in raw_events for audit).
            if reply.text and reply.error:
                reply.error = None
        except Exception as exc:  # noqa: BLE001
            reply.error = str(exc)
        finally:
            reply.latency_ms = (time.perf_counter() - start) * 1000
        return reply

    # ------------------------------------------------------------------- llm
    def llm(self, user: str, system: str | None = None) -> dict[str, Any]:
        """Pass-through LLM call used to power LLM-as-judge scorers."""
        sid = self._require_session()
        payload: dict[str, Any] = {"sessionId": sid, "user": user}
        if system:
            payload["system"] = system
        r = self._http.post(f"{self.base_url}/api/llm", json=payload, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # -------------------------------------------------------------- ui-event
    def ui_event(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        sid = self._require_session()
        r = self._http.post(
            f"{self.base_url}/api/ui-event",
            json={"sessionId": sid, "kind": kind, "payload": payload},
            timeout=self.timeout,
        )
        r.raise_for_status()
        self._state_cache = None  # state changed
        return r.json()


def _iter_sse(response: requests.Response):
    """Yield (event, data_dict) tuples from an SSE response stream."""
    event = "message"
    data_lines: list[str] = []
    for raw in response.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        line = raw.rstrip("\r")
        if line == "":  # frame boundary
            if data_lines:
                payload = "\n".join(data_lines)
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    data = {"text": payload}
                yield event, data
            event, data_lines = "message", []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
    if data_lines:  # trailing frame without blank line
        try:
            yield event, json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            yield event, {"text": "\n".join(data_lines)}
