# Sample run (committed evidence)

`sample_run_52cases/` is a real, committed run of all 52 cases (the live run from
2026-06-27) so reviewers can see actual results without a token:

- **`report.html`** — open in a browser: per-category pass-rates, per-scorer means,
  and every reply with its scores + reasoning.
- **`report.json`** — the structured log: each rep's prompt, reply, latency,
  tool-rounds, and every scorer's `{score, label, reasoning}`. (This replaces a
  raw run log.)
- **`scored.csv`** — one row per rep, scores per scorer, for spreadsheet triage.

The written interpretation of these numbers is in
[`../docs/execution-results.md`](../docs/execution-results.md). Fresh runs are
written to `outputs/<timestamp>/` (git-ignored).