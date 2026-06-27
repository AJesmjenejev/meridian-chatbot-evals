"""Tests for runner error handling: --fail-fast vs record-and-continue."""

from __future__ import annotations

import pytest

from meridian_evals.mock import MockClient
from meridian_evals.models import EvalCase
from meridian_evals.runner import EvalRunError, run_case
from meridian_evals.scorers.registry import ScoreContext

from .conftest import FIXTURES


def _client() -> MockClient:
    return MockClient(str(FIXTURES / "demo_cassette.json"))


def _unrecorded_case() -> EvalCase:
    # A prompt not present in the cassette makes MockClient return an error reply.
    return EvalCase(
        case_id="missing",
        category="t",
        user_input="THIS PROMPT IS NOT IN THE CASSETTE",
        scorers=["rule/no_secret_leak"],
    )


def test_fail_fast_raises_classified_error():
    client = _client()
    ctx = ScoreContext(client=client, state={})
    with pytest.raises(EvalRunError) as ei:
        run_case(client, _unrecorded_case(), ctx, reps=1, fail_fast=True)
    assert ei.value.kind == "chat_error"
    assert ei.value.case_id == "missing"


def test_default_records_error_and_continues():
    client = _client()
    ctx = ScoreContext(client=client, state={})
    results = run_case(client, _unrecorded_case(), ctx, reps=1, fail_fast=False)
    assert len(results) == 1
    assert results[0].error  # recorded, not raised
