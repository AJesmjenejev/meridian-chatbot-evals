# Meridian Banking Chatbot — Test Harness

A small, runnable evaluation harness for the **Meridian** banking assistant. It
sends labelled prompts to the live chatbot, scores each reply with a mix of
**rule-based** checks and **LLM-as-judge** scorers, repeats cases to measure
**non-determinism**, and writes console / JSON / CSV / HTML reports.

> **Finding in one line:** the assistant is *safe but not yet grounded* — it never
> leaked a PIN/PAN and resists injection, but it confabulates fees, over-promises
> eligibility, and serves stale state after actions; its variance concentrates on
> adversarial prompts. See [`docs/execution-results.md`](docs/execution-results.md).

> **Start here:** a committed sample run is in
> [`results/sample_run_52cases/`](results/sample_run_52cases/) (open `report.html`) —
> that snapshot predates the `helpfulness` and `input_robustness` suites, so it
> covers 52 of the current 65 cases; re-run the harness to regenerate a full run.

> Submission for the 2nd-round exercise. The reasoning lives in
> [`docs/approach-note.md`](docs/approach-note.md),
> [`docs/test-cases.md`](docs/test-cases.md),
> [`docs/manual-exploration.md`](docs/manual-exploration.md) (qualitative evidence
> from the recorded session),
> [`docs/execution-results.md`](docs/execution-results.md),
> [`docs/scaling-strategy.md`](docs/scaling-strategy.md) and
> [`docs/ai-tool-usage-log.md`](docs/ai-tool-usage-log.md). This README is the
> "how to run it" part.

## Run it in under 5 minutes

```bash
# 1. install into a venv (deps: requests + pyyaml only)
python3 -m venv .venv && source .venv/bin/activate && pip install -e .
#   (uv: uv venv && source .venv/bin/activate && uv pip install -e .)
#   plain `pip install -e .` fails on Homebrew Python (PEP 668) — use the venv

# 2. point it at your session
cp .env.example .env        # then edit: MERIDIAN_BASE_URL + MERIDIAN_TOKEN
#    (token = the value after ?token= in your invitation link)

# 3. smoke-test connectivity (redeem + one chat + one judge call + state)
python -m meridian_evals --smoke

# 4. run everything
python -m meridian_evals datasets/*.yaml
#    → outputs/<timestamp>/report.html | report.json | scored.csv
#    → outputs/latest/ symlinks the newest run
```

Run a single suite or change repetition count:

```bash
python -m meridian_evals datasets/safety.yaml --reps 5
```

## Tests & CI

```bash
pip install -e ".[dev]"   # adds pytest
pytest -q                  # scorers, dataset validation, judge parsing, offline run
```

`pytest` covers the load-bearing logic with no network: the `no_secret_leak`
guard (masked cards / IBANs / PIN false positives), the cents-aware oracle
match, dataset validation (unknown scorers, duplicate IDs, malformed actions),
judge JSON extraction, and an end-to-end `--mock` run. GitHub Actions
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the suite plus the
offline mock run on Python 3.10 and 3.12.

## What it tests

65 labelled cases across eleven datasets (see [`datasets/`](datasets/) and
[`docs/test-cases.md`](docs/test-cases.md) for the full labelled set + rationale):

| Dataset | Probes |
|---|---|
| `grounding.yaml` | balance, IBAN, BIC, card limit/expiry, recent tx, spend aggregation |
| `safety.yaml` | PIN/PAN refusal, prompt injection, system-prompt exfiltration, cross-customer, PIN-policy accuracy, out-of-scope |
| `hallucination.yaml` | non-existent branch / crypto / business account / invented fee / phantom transfer |
| `actions.yaml` | lock / unlock card + state-aware status |
| `products_branches.yaml` | wealth/insurance detail, **tier eligibility & over-count**, branch finder |
| `fees.yaml` | foreign / ATM / overdraft / replacement / expedited fees (oracle from UI) |
| `limits.yaml` | daily-spend vs ATM limit (oracle from card state) |
| `stale_context.yaml` | **action-then-ask**: lock / limit / travel via `/api/ui-event`, scored vs refreshed state |
| `helpfulness.yaml` | how-to guidance (lock card, send money), contactless limit, ambiguous-query handling, product discovery |
| `input_robustness.yaml` | **negative inputs**: empty, gibberish, oversized (≈1 kchar), non-English (German), SQL/XSS/shell-injection chars |
| `robustness.yaml` | same-prompt consistency (high reps), multi-turn context, paraphrase invariance |

## How scoring works

* **Rule-based** (`meridian_evals/scorers/rule_based.py`): ground-truth match vs
  the live `/api/state` oracle (amounts compared numerically, cents-aware),
  substring/refusal checks, a `no_secret_leak` guard that fails on any PAN/PIN
  disclosure, and a latency budget.
* **LLM-as-judge** (`meridian_evals/scorers/llm_judge.py`): answer-correctness,
  grounding/contradiction, refusal-appropriateness and multi-turn context, each
  run through `POST /api/llm` and returning a structured
  `{score, label, reasoning}`.
* **Consistency**: every case runs `reps` times; the report shows per-category
  pass-rate and flags **flaky** cases (0 < pass-rate < 1) — because the bot is a
  real LLM and varies run-to-run.

The judge's reliability, the binary-scoring rationale, the `confidence=0.7`
heuristic, known failure modes and a calibration plan are written up in
[`docs/judge-methodology.md`](docs/judge-methodology.md).

Ground truth is **never hard-coded to a balance** — money is dynamic (receiving
salary moves it), so datasets reference the oracle via `{{ accounts.0.balance_cents | euros }}`
templating that resolves against `/api/state` at run time.

## Notes / gotchas

* `GET /api/state` returns financial JSON; if it's unavailable on your network
  there are two escape hatches: `MERIDIAN_STATE_FILE=captured_state.json`
  (capture once from a browser) and `MERIDIAN_VERIFY_SSL=false` (if the network's
  TLS root CA isn't trusted). Neither is needed on a direct connection.
* `/api/llm` is itself scope-guarded to banking topics, so judge prompts are
  framed as *grading a banking assistant* to avoid being deflected.

## Layout

```
meridian_evals/        # the harness (client, scorers, runner, report, mock)
datasets/              # the labelled test-case set (YAML)
fixtures/              # offline mock cassettes + demo datasets (--mock)
scripts/               # capture_metadata.py (full session snapshot)
results/               # committed sample run (report.html/json/csv) — visible evidence
tests/                 # pytest: scorers, dataset validation, judge parsing, offline mock run
docs/                  # approach, results, scaling, AI-tool log, test-cases, manual-exploration, how-to-run, judge-methodology
```

**Offline mode (no token):** replay a recorded/authored cassette —
`python -m meridian_evals --mock fixtures/demo_cassette.json fixtures/mock_demo.yaml`.
Record one from a live run with `--record`. See
[`docs/how-to-run.md`](docs/how-to-run.md) §5.