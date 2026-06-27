"""Shared test helpers."""

from __future__ import annotations

from pathlib import Path

from meridian_evals.models import ChatReply, EvalCase
from meridian_evals.scorers.registry import ScoreContext

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "fixtures"
DATASETS = REPO_ROOT / "datasets"


def make_case(**kwargs) -> EvalCase:
    base = dict(case_id="t", category="test", user_input="hi", scorers=["rule/contains"])
    base.update(kwargs)
    return EvalCase(**base)


def make_reply(text: str, **kwargs) -> ChatReply:
    return ChatReply(text=text, **kwargs)


def make_ctx(state: dict | None = None) -> ScoreContext:
    return ScoreContext(client=None, state=state or {})
