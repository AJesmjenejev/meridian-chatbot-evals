#!/usr/bin/env python3
"""Capture a complete metadata snapshot of a Meridian session into one JSON.

Pulls everything an eval reviewer might want:
  - redeemed sessionId
  - full /api/state (account, card, transactions, customer, ui, expiry)
  - the three catalogues (fee_schedule, feature_map, policy_map) when reachable
  - a sample /api/chat turn with its RAW SSE events (tool_round/chunk/done) +
    parsed reply, latency, threadId, turn
  - a sample /api/llm pass-through call with its reasoning_trace + latency

Usage:
    python scripts/capture_metadata.py                 # writes metadata_<ts>.json
    python scripts/capture_metadata.py --probe "Lock my card"

Env: MERIDIAN_BASE_URL, MERIDIAN_TOKEN (+ optional MERIDIAN_VERIFY_SSL=false).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from meridian_evals.client import MeridianClient  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", default="What's my balance?", help="sample chat message")
    ap.add_argument("--out", default=None, help="output path")
    args = ap.parse_args()

    base = os.environ.get("MERIDIAN_BASE_URL")
    token = os.environ.get("MERIDIAN_TOKEN")
    if not base or not token:
        sys.exit("Set MERIDIAN_BASE_URL and MERIDIAN_TOKEN.")
    verify = os.environ.get("MERIDIAN_VERIFY_SSL", "true").lower() not in ("false", "0", "no")
    c = MeridianClient(base, token, verify_ssl=verify)

    meta: dict = {"captured_at": dt.datetime.now().isoformat(timespec="seconds")}
    meta["session_id"] = c.redeem()

    try:
        meta["state"] = c.get_state(refresh=True)
    except Exception as exc:  # noqa: BLE001
        meta["state"] = {"error": str(exc)}

    meta["catalogues"] = {}
    for name in ("fee_schedule", "feature_map", "policy_map"):
        try:
            meta["catalogues"][name] = c.catalogue(name)
        except Exception as exc:  # noqa: BLE001
            meta["catalogues"][name] = {"error": str(exc)}

    reply = c.chat(args.probe)
    meta["sample_chat"] = {
        "message": args.probe,
        "reply": reply.text,
        "thread_id": reply.thread_id,
        "turn": reply.turn,
        "tool_rounds": reply.tool_rounds,
        "latency_ms": round(reply.latency_ms, 1),
        "error": reply.error,
        "raw_sse_events": reply.raw_events,  # full event stream
    }

    try:
        llm = c.llm(
            user="Return JSON {\"ok\":1} if 'IBAN' is a banking term.",
            system="You are a grader. Output only JSON.",
        )
        meta["sample_llm"] = llm  # includes text, latency_ms, reasoning_trace
    except Exception as exc:  # noqa: BLE001
        meta["sample_llm"] = {"error": str(exc)}

    out = args.out or f"metadata_{dt.datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False)
    print(f"Wrote {out}")
    print("  session:", meta["session_id"])
    st = meta.get("state", {})
    if isinstance(st, dict) and "accounts" in st:
        print(
            "  balance_cents:",
            st["accounts"][0]["balance_cents"],
            "| card.locked:",
            st["cards"][0]["locked"],
        )
    print(
        "  chat tool_rounds:",
        meta["sample_chat"]["tool_rounds"],
        "| latency_ms:",
        meta["sample_chat"]["latency_ms"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
