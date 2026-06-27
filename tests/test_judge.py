"""Tests for the LLM-judge JSON extraction (the part we control deterministically)."""

from __future__ import annotations

from meridian_evals.scorers.llm_judge import _extract_json


def test_plain_json():
    assert _extract_json('{"score": 1, "label": "ok"}') == {"score": 1, "label": "ok"}


def test_code_fenced_json():
    raw = '```json\n{"score": 0, "label": "bad"}\n```'
    assert _extract_json(raw) == {"score": 0, "label": "bad"}


def test_json_embedded_in_prose():
    raw = 'Here is my verdict: {"score": 1, "reasoning": "fine"} hope that helps'
    assert _extract_json(raw) == {"score": 1, "reasoning": "fine"}


def test_unparsable_returns_none():
    assert _extract_json("the assistant did great, score it 1") is None
