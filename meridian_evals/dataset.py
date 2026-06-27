"""Load and validate YAML test-case datasets.

Validation is deliberately strict: an eval harness is only as trustworthy as
its inputs, so we fail loudly on garbage (unknown scorer names, duplicate case
IDs, malformed actions) at load time rather than producing a silently-wrong
report.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import EvalCase
from .scorers import all_scorers

# Scorers that are meaningless without a specific expected field. Each value is
# an "any-of" group: the case must supply at least one of these keys in
# ``expected``, otherwise the scorer would silently score vacuous (None) and the
# case would look covered when it is not. This is the "expected schema per
# scorer" guard.
_REQUIRED_EXPECTED: dict[str, tuple[str, ...]] = {
    "rule/contains": ("must_contain", "must_not_contain"),
    "rule/ground_truth_match": ("ground_truth_path",),
    "rule/numeric_close": ("expected_number",),
    "rule/refusal": ("must_refuse",),
    "rule/latency": ("max_latency_ms",),
    "llm/answer_correctness": ("expected_answer", "complete_answer"),
}


def _validate_actions(path: Path, case_id: str, field: str, actions: Any) -> list[dict]:
    if not isinstance(actions, list):
        raise ValueError(f"{path}: case {case_id} {field} must be a list")
    out: list[dict] = []
    for j, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ValueError(f"{path}: case {case_id} {field}[{j}] must be a mapping with a 'kind'")
        if not action.get("kind"):
            raise ValueError(f"{path}: case {case_id} {field}[{j}] missing 'kind'")
        payload = action.get("payload")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError(f"{path}: case {case_id} {field}[{j}] payload must be a mapping")
        out.append(action)
    return out


def load_dataset(path: str | Path) -> tuple[dict[str, Any], list[EvalCase]]:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping")
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict) or not metadata.get("name"):
        raise ValueError(f"{path}: metadata.name is required (non-empty)")
    known_scorers = set(all_scorers())
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    for i, c in enumerate(raw.get("cases", [])):
        if "case_id" not in c:
            raise ValueError(f"{path}: case #{i} missing case_id")
        case_id = c["case_id"]
        if case_id in seen_ids:
            raise ValueError(f"{path}: duplicate case_id {case_id!r}")
        seen_ids.add(case_id)
        if not c.get("user_input") and not c.get("turns"):
            raise ValueError(f"{path}: case {case_id} has no user_input/turns")
        scorers = c.get("scorers")
        if not scorers:
            raise ValueError(f"{path}: case {case_id} has no scorers")
        unknown = [s for s in scorers if s not in known_scorers]
        if unknown:
            raise ValueError(
                f"{path}: case {case_id} references unknown scorer(s) {unknown}; "
                f"registered: {sorted(known_scorers)}"
            )
        expected = c.get("expected", {}) or {}
        for s in scorers:
            req = _REQUIRED_EXPECTED.get(s)
            if req and not any(k in expected for k in req):
                raise ValueError(
                    f"{path}: case {case_id} scorer {s!r} requires one of {list(req)} in 'expected'"
                )
        if "llm/context_retention" in scorers and not c.get("turns"):
            raise ValueError(
                f"{path}: case {case_id} scorer 'llm/context_retention' requires multi-turn 'turns'"
            )
        setup = _validate_actions(path, case_id, "setup_actions", c.get("setup_actions", []))
        teardown = _validate_actions(
            path, case_id, "teardown_actions", c.get("teardown_actions", [])
        )
        cases.append(
            EvalCase(
                case_id=case_id,
                category=c.get("category", metadata.get("name", "uncategorized")),
                user_input=c.get("user_input"),
                turns=list(c.get("turns", [])),
                reps=int(c.get("reps", 1)),
                expected=expected,
                scorers=list(scorers),
                rationale=c.get("rationale", ""),
                setup_actions=setup,
                teardown_actions=teardown,
            )
        )
    return metadata, cases
