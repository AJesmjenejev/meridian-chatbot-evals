"""Scorer registry and built-in scorers.

Importing this package registers every built-in scorer (the modules call
``@register_scorer`` at import time).
"""

from . import llm_judge, rule_based  # noqa: F401  (import side-effects register scorers)
from .registry import ScoreContext, all_scorers, get_scorer, register_scorer

__all__ = [
    "ScoreContext",
    "all_scorers",
    "get_scorer",
    "register_scorer",
    "rule_based",
    "llm_judge",
]
