"""CLI entry point.

python -m meridian_evals --smoke
python -m meridian_evals datasets/*.yaml
python -m meridian_evals datasets/safety.yaml --reps 5 --out outputs
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

from .client import MeridianClient
from .dataset import load_dataset
from .report import print_console, summarize, write_reports
from .runner import run_dataset


def _load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _client() -> MeridianClient:
    base = os.environ.get("MERIDIAN_BASE_URL")
    token = os.environ.get("MERIDIAN_TOKEN")
    if not base or not token:
        sys.exit("Set MERIDIAN_BASE_URL and MERIDIAN_TOKEN (see .env.example).")
    verify = os.environ.get("MERIDIAN_VERIFY_SSL", "true").lower() not in ("false", "0", "no")
    return MeridianClient(
        base,
        token,
        state_file=os.environ.get("MERIDIAN_STATE_FILE"),
        verify_ssl=verify,
    )


def _smoke(client: MeridianClient) -> int:
    print("Redeeming token…")
    print("  sessionId:", client.redeem())
    print("Chat: 'What is my current balance?'")
    reply = client.chat("What is my current balance?")
    print("  reply:", reply.text or f"<error: {reply.error}>")
    print("  latency_ms:", round(reply.latency_ms))
    print("LLM judge ping…")
    try:
        j = client.llm(
            user="Return JSON {\"score\":1} if 'balance' is a banking term.",
            system="You are a grader. Output only JSON.",
        )
        print("  llm:", j.get("text"))
    except Exception as exc:  # noqa: BLE001 - backend may be 500-ing
        print("  llm: unavailable —", exc)
    try:
        st = client.get_state()
        print("  state keys:", list(st.keys()))
    except Exception as exc:  # noqa: BLE001
        print("  state: unavailable —", exc)
    return 0 if reply.text else 1


def main(argv: list[str] | None = None) -> int:
    # The console summary uses €, bar glyphs, etc.; force UTF-8 so it doesn't
    # crash on a legacy code page (e.g. Windows cp1252). Reports are UTF-8 anyway.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(prog="meridian-evals")
    ap.add_argument("datasets", nargs="*", help="dataset YAML files or globs")
    ap.add_argument("--smoke", action="store_true", help="connectivity smoke test")
    ap.add_argument("--reps", type=int, default=None, help="override reps per case")
    ap.add_argument("--out", default="outputs", help="output root dir")
    ap.add_argument("--env", default=".env", help="dotenv file")
    ap.add_argument(
        "--mock", metavar="CASSETTE", help="replay a cassette offline (no network/token)"
    )
    ap.add_argument(
        "--record",
        metavar="CASSETTE",
        help="run live AND save responses to a cassette for later --mock",
    )
    ap.add_argument(
        "--fail-fast",
        action="store_true",
        help="abort on the first chat/scorer/ui-event error instead of recording it",
    )
    args = ap.parse_args(argv)

    if args.mock:
        from .mock import MockClient

        client: object = MockClient(args.mock)
        print(f"[mock] replaying cassette {args.mock} — no network")
    else:
        _load_dotenv(args.env)
        client = _client()
        if args.record:
            from .mock import RecordingClient

            client = RecordingClient(client, args.record)
            print(f"[record] saving responses to {args.record}")

    if args.smoke:
        return _smoke(client)

    paths: list[str] = []
    for pat in args.datasets or ["datasets/*.yaml"]:
        paths.extend(sorted(glob.glob(pat)))
    if not paths:
        sys.exit("No dataset files matched.")

    all_cases = []
    seen: dict[str, str] = {}
    for p in paths:
        meta, cases = load_dataset(p)
        for c in cases:
            if c.case_id in seen:
                sys.exit(
                    f"Duplicate case_id {c.case_id!r} in {p} (already defined in {seen[c.case_id]})"
                )
            seen[c.case_id] = p
        print(f"Loaded {len(cases)} cases from {p}")
        all_cases.extend(cases)

    print(f"\nRunning {len(all_cases)} cases…")
    results = run_dataset(client, all_cases, reps_override=args.reps, fail_fast=args.fail_fast)
    out = write_reports(results, out_root=args.out)
    print_console(summarize(results))
    print(f"Reports written to {out}/ (report.html, report.json, scored.csv)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
