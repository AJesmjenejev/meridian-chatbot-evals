"""Scorer registry.

A scorer is a callable ``fn(case, reply, ctx) -> EvaluationScore`` registered
under a name like ``rule/ground_truth_match`` or ``llm/answer_correctness``.
Datasets reference scorers by these names.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..models import ChatReply, EvalCase, EvaluationScore

_REGISTRY: dict[str, Scorer] = {}


@dataclass
class ScoreContext:
    """Everything a scorer might need beyond the case + reply."""

    client: Any  # MeridianClient (avoid import cycle)
    state: dict[str, Any]


Scorer = Callable[[EvalCase, ChatReply, ScoreContext], EvaluationScore]


def register_scorer(name: str) -> Callable[[Scorer], Scorer]:
    def deco(fn: Scorer) -> Scorer:
        if name in _REGISTRY:
            raise ValueError(f"scorer already registered: {name}")
        _REGISTRY[name] = fn
        return fn

    return deco


def get_scorer(name: str) -> Scorer:
    if name not in _REGISTRY:
        raise KeyError(f"unknown scorer {name!r}; registered: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def all_scorers() -> list[str]:
    return sorted(_REGISTRY)
