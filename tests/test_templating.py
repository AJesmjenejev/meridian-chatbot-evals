"""Tests for the {{ oracle }} templating used to keep expectations live."""

from __future__ import annotations

from meridian_evals.templating import render, render_expected


def test_euros_filter():
    state = {"accounts": [{"balance_cents": 516883}]}
    assert render("{{ accounts.0.balance_cents | euros }}", state) == "€5,168.83"


def test_raw_value_no_filter():
    state = {"cards": [{"id": "card_1"}]}
    assert render("{{ cards.0.id }}", state) == "card_1"


def test_missing_path_renders_empty():
    assert render("x={{ accounts.5.balance_cents | euros }}", {}) == "x="


def test_render_expected_lists_and_scalars():
    state = {"accounts": [{"balance_cents": 100000}]}
    expected = {
        "must_contain": ["{{ accounts.0.balance_cents | euros }}", "literal"],
        "tolerance": 0.01,
    }
    out = render_expected(expected, state)
    assert out["must_contain"] == ["€1,000.00", "literal"]
    assert out["tolerance"] == 0.01
