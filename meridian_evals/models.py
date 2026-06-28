"""Core data models, kept deliberately small (stdlib dataclasses only).

An ``EvaluationScore`` carries ``score`` / ``label`` / ``confidence`` /
``reasoning``; a per-row result carries the captured chatbot output plus the
scores for that reply.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvaluationScore:
    """Result of a single scorer on a single chatbot reply.

    score == None means the scorer did not apply to this case (it was skipped),
    which is excluded from pass-rate aggregation rather than counted as a fail.
    """

    score: float | None
    label: str | None = None
    confidence: float = 1.0
    reasoning: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool | None:
        if self.score is None:
            return None
        return self.score >= 0.5


@dataclass
class ChatReply:
    """Parsed result of one POST /api/chat call."""

    text: str
    thread_id: str | None = None
    turn: int | None = None
    tool_rounds: int = 0
    latency_ms: float = 0.0
    error: str | None = None
    raw_events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EvalCase:
    """One labelled test case."""

    case_id: str
    category: str
    user_input: str | None = None
    turns: list[str] = field(default_factory=list)  # multi-turn; overrides user_input
    reps: int = 1
    expected: dict[str, Any] = field(default_factory=dict)
    scorers: list[str] = field(default_factory=list)
    rationale: str = ""
    # UI actions run via /api/ui-event before/after the chat turns. Used by the
    # stale-context family: mutate state, then check the bot reflects it.
    # Each action is {"kind": "...", "payload": {...}}; payload string values
    # may use {{ oracle }} templating (e.g. card_id: "{{ cards.0.id }}").
    setup_actions: list[dict[str, Any]] = field(default_factory=list)
    teardown_actions: list[dict[str, Any]] = field(default_factory=list)

    def messages(self) -> list[str]:
        if self.turns:
            return self.turns
        return [self.user_input or ""]


@dataclass
class RepResult:
    """Scores for one repetition of one case."""

    case_id: str
    category: str
    rep: int
    prompt: str
    reply: str
    latency_ms: float
    thread_id: str | None
    tool_rounds: int
    error: str | None
    scores: dict[str, EvaluationScore]

    @property
    def rep_passed(self) -> bool | None:
        """A rep passes only if every applicable scorer passed."""
        applicable = [s.passed for s in self.scores.values() if s.passed is not None]
        if not applicable:
            return None
        return all(applicable)
