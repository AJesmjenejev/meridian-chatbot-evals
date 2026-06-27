"""Tests for dataset loading + the strict validation that guards garbage-in."""

from __future__ import annotations

import glob

import pytest

from meridian_evals.dataset import load_dataset

from .conftest import DATASETS

_META = "metadata:\n  name: test\n"


def _write(tmp_path, body: str):
    """Write a dataset YAML, prepending a minimal metadata block if absent."""
    p = tmp_path / "ds.yaml"
    if "metadata:" not in body:
        body = _META + body
    p.write_text(body, encoding="utf-8")
    return p


def test_all_shipped_datasets_load():
    files = sorted(glob.glob(str(DATASETS / "*.yaml")))
    assert files, "no datasets found"
    total = 0
    for f in files:
        _meta, cases = load_dataset(f)
        total += len(cases)
    assert total == 65  # keep README/docs honest about the count


def test_rejects_unknown_scorer(tmp_path):
    ds = _write(
        tmp_path,
        """
cases:
  - case_id: c1
    user_input: hi
    scorers: [rule/does_not_exist]
""",
    )
    with pytest.raises(ValueError, match="unknown scorer"):
        load_dataset(ds)


def test_rejects_duplicate_case_id(tmp_path):
    ds = _write(
        tmp_path,
        """
cases:
  - case_id: dup
    user_input: hi
    scorers: [rule/no_secret_leak]
  - case_id: dup
    user_input: hey
    scorers: [rule/no_secret_leak]
""",
    )
    with pytest.raises(ValueError, match="duplicate case_id"):
        load_dataset(ds)


def test_rejects_missing_scorers(tmp_path):
    ds = _write(
        tmp_path,
        """
cases:
  - case_id: c1
    user_input: hi
""",
    )
    with pytest.raises(ValueError, match="no scorers"):
        load_dataset(ds)


def test_rejects_no_input(tmp_path):
    ds = _write(
        tmp_path,
        """
cases:
  - case_id: c1
    scorers: [rule/no_secret_leak]
""",
    )
    with pytest.raises(ValueError, match="no user_input/turns"):
        load_dataset(ds)


def test_rejects_malformed_setup_action(tmp_path):
    ds = _write(
        tmp_path,
        """
cases:
  - case_id: c1
    user_input: hi
    scorers: [rule/no_secret_leak]
    setup_actions:
      - payload: {card_id: x}
""",
    )
    with pytest.raises(ValueError, match="missing 'kind'"):
        load_dataset(ds)


def test_rejects_scorer_missing_required_expected(tmp_path):
    # rule/numeric_close is meaningless without expected_number.
    ds = _write(
        tmp_path,
        """
cases:
  - case_id: c1
    user_input: how much?
    scorers: [rule/numeric_close]
    expected: {}
""",
    )
    with pytest.raises(ValueError, match="requires one of"):
        load_dataset(ds)


def test_rejects_context_retention_without_turns(tmp_path):
    ds = _write(
        tmp_path,
        """
cases:
  - case_id: c1
    user_input: single turn only
    scorers: [llm/context_retention]
""",
    )
    with pytest.raises(ValueError, match="requires.*turns"):
        load_dataset(ds)


def test_rejects_empty_metadata(tmp_path):
    p = tmp_path / "ds.yaml"
    p.write_text(
        """
cases:
  - case_id: c1
    user_input: hi
    scorers: [rule/no_secret_leak]
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="metadata.name"):
        load_dataset(p)


def test_valid_dataset_with_actions_loads(tmp_path):
    ds = _write(
        tmp_path,
        """
cases:
  - case_id: c1
    user_input: hi
    scorers: [rule/contains]
    expected:
      must_contain: ["hello"]
    setup_actions:
      - kind: lock_card
        payload: {card_id: "{{ cards.0.id }}"}
""",
    )
    _meta, cases = load_dataset(ds)
    assert cases[0].setup_actions[0]["kind"] == "lock_card"
