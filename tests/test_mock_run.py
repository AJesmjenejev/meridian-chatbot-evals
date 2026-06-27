"""End-to-end smoke test of the harness over the offline demo cassette.

This exercises load_dataset -> run_dataset -> consistency -> report writing with
no network, and asserts the three pass / one-deliberate-fail outcome documented
in fixtures/mock_demo.yaml.
"""

from __future__ import annotations

import json

from meridian_evals.dataset import load_dataset
from meridian_evals.mock import MockClient
from meridian_evals.report import summarize, write_reports
from meridian_evals.runner import consistency, run_dataset

from .conftest import FIXTURES


def _run():
    client = MockClient(str(FIXTURES / "demo_cassette.json"))
    _meta, cases = load_dataset(str(FIXTURES / "mock_demo.yaml"))
    return cases, run_dataset(client, cases, reps_override=1)


def test_mock_demo_outcomes():
    _cases, results = _run()
    cons = consistency(results)
    assert cons["demo_balance_pass"]["pass_rate"] == 1.0
    assert cons["demo_fee_pass"]["pass_rate"] == 1.0
    assert cons["demo_pin_refuse_pass"]["pass_rate"] == 1.0
    # The leak case is authored to FAIL — proves the guard fires end-to-end.
    assert cons["demo_leak_fail"]["pass_rate"] == 0.0


def test_reports_are_written_and_valid(tmp_path):
    _cases, results = _run()
    out = write_reports(results, out_root=str(tmp_path))
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["summary"]["total_cases"] == 4
    assert (out / "report.html").read_text(encoding="utf-8").startswith("<!doctype html>")
    assert (out / "scored.csv").exists()


def test_summary_has_no_unexpected_errors():
    _cases, results = _run()
    summary = summarize(results)
    assert summary["errors"] == []
