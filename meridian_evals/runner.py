"""Execution engine: run each case N times, score every reply, collect results."""

from __future__ import annotations

import dataclasses
import statistics
from typing import Any

from .client import MeridianClient
from .models import EvalCase, EvaluationScore, RepResult
from .scorers.registry import ScoreContext, get_scorer
from .templating import render, render_expected


class EvalRunError(RuntimeError):
    """A run-time failure raised in --fail-fast mode, with structured context.

    ``kind`` classifies the failure (``chat_error``, ``scorer_error``,
    ``ui_event_error``) so callers/CI can react to the category, not a string.
    """

    def __init__(self, kind: str, case_id: str, detail: str) -> None:
        self.kind = kind
        self.case_id = case_id
        self.detail = detail
        super().__init__(f"[{kind}] case {case_id}: {detail}")


def _run_actions(
    client: MeridianClient,
    actions: list[dict],
    state: dict,
    *,
    case_id: str = "",
    fail_fast: bool = False,
) -> dict | None:
    """Execute UI actions via /api/ui-event, templating payloads against state.

    Returns the authoritative post-action state from the last ui-event response
    (the response carries ``state``), so stale-context cases work even when
    GET /api/state is unavailable.
    """
    latest: dict | None = None
    for action in actions:
        kind = action["kind"]
        payload = {
            k: (render(v, state) if isinstance(v, str) else v)
            for k, v in (action.get("payload") or {}).items()
        }
        try:
            resp = client.ui_event(kind, payload)
            if isinstance(resp, dict) and resp.get("state"):
                latest = resp["state"]
                state = latest
        except Exception as exc:  # noqa: BLE001
            if fail_fast:
                raise EvalRunError("ui_event_error", case_id, f"{kind}: {exc}") from exc
            print(f"    ! ui-event {kind} failed: {exc}")
    return latest


def _load_state(client: MeridianClient) -> dict[str, Any]:
    """Best-effort oracle load; harness still runs if state is unreachable."""
    try:
        return client.get_state()
    except Exception as exc:  # noqa: BLE001
        print(f"  ! /api/state unavailable ({exc}); ground-truth scorers vacuous")
        return {}


def run_case(
    client: MeridianClient,
    case: EvalCase,
    ctx: ScoreContext,
    reps: int,
    *,
    fail_fast: bool = False,
) -> list[RepResult]:
    results: list[RepResult] = []
    # Stale-context setup: mutate state via UI actions, then refresh the oracle
    # so expectations reflect the POST-action state (the bot must too).
    if case.setup_actions:
        new_state = _run_actions(
            client, case.setup_actions, ctx.state, case_id=case.case_id, fail_fast=fail_fast
        )
        if new_state:
            ctx.state = new_state  # authoritative post-action state from response
        else:
            try:
                ctx.state = client.get_state(refresh=True)
            except Exception:  # noqa: BLE001
                pass
    # Resolve {{ oracle }} placeholders against the live state so expectations
    # track the pinned profile (e.g. a balance that moved after salary).
    case = dataclasses.replace(case, expected=render_expected(case.expected, ctx.state))
    messages = case.messages()
    for rep in range(reps):
        thread_id = None
        reply = None
        # Replay all turns on one thread; only the final reply is scored.
        for msg in messages:
            reply = client.chat(msg, thread_id=thread_id)
            thread_id = reply.thread_id
        assert reply is not None
        if reply.error and fail_fast:
            raise EvalRunError("chat_error", case.case_id, reply.error)
        scores = {}
        for scorer_name in case.scorers:
            try:
                scores[scorer_name] = get_scorer(scorer_name)(case, reply, ctx)
            except Exception as exc:  # noqa: BLE001
                if fail_fast:
                    raise EvalRunError(
                        "scorer_error", case.case_id, f"{scorer_name}: {exc}"
                    ) from exc
                scores[scorer_name] = EvaluationScore(
                    None, label="scorer_error", reasoning=str(exc)
                )
        results.append(
            RepResult(
                case_id=case.case_id,
                category=case.category,
                rep=rep,
                prompt=messages[-1],
                reply=reply.text,
                latency_ms=reply.latency_ms,
                thread_id=reply.thread_id,
                tool_rounds=reply.tool_rounds,
                error=reply.error,
                scores=scores,
            )
        )
    # Restore session state (e.g. unlock card, reset limit) so later cases
    # aren't polluted by this one's setup.
    if case.teardown_actions:
        restored = _run_actions(
            client, case.teardown_actions, ctx.state, case_id=case.case_id, fail_fast=fail_fast
        )
        if restored:
            ctx.state = restored
    return results


def run_dataset(
    client: MeridianClient,
    cases: list[EvalCase],
    reps_override: int | None = None,
    *,
    fail_fast: bool = False,
) -> list[RepResult]:
    ctx = ScoreContext(client=client, state=_load_state(client))
    all_results: list[RepResult] = []
    for case in cases:
        reps = reps_override or case.reps
        print(f"  · {case.case_id} ({case.category}) x{reps}")
        all_results.extend(run_case(client, case, ctx, reps, fail_fast=fail_fast))
    return all_results


def consistency(results: list[RepResult]) -> dict[str, dict[str, Any]]:
    """Per-case pass-rate + flakiness across reps (characterises non-determinism)."""
    by_case: dict[str, list[RepResult]] = {}
    for r in results:
        by_case.setdefault(r.case_id, []).append(r)
    out = {}
    for case_id, reps in by_case.items():
        verdicts = [r.rep_passed for r in reps if r.rep_passed is not None]
        passes = sum(1 for v in verdicts if v)
        rate = passes / len(verdicts) if verdicts else None
        flaky = rate is not None and 0.0 < rate < 1.0
        out[case_id] = {
            "category": reps[0].category,
            "reps": len(reps),
            "pass_rate": rate,
            "flaky": flaky,
            "mean_latency_ms": round(statistics.mean(r.latency_ms for r in reps), 1),
        }
    return out
