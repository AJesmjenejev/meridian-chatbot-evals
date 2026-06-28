# Scaling & strategy note

How I'd take this from a one-off harness to something a team trusts as a gate.

## Regression protection

* **Datasets are the contract.** Test cases live in version-controlled YAML, so
  adding/changing a case is a reviewable diff, not a code change. New behaviours
  ship with new cases in the same PR.
* **Oracle-first expectations.** Because facts are read from `/api/state` at run
  time, the suite doesn't rot when the seed profile changes — it only fails when
  the *bot* diverges from truth. That keeps regressions meaningful.
* **Golden tier for determinism.** Split scorers into rule-based (deterministic,
  safe to gate hard) and judge-based (probabilistic, gate on pass-rate). A
  refusal regression on `no_secret_leak` should hard-fail; a 1-point wobble on
  an LLM-judged helpfulness score should not.

## CI gating

* Run `safety.yaml` + the `no_secret_leak` guard on **every** PR — these are the
  non-negotiables (PIN/PAN/injection). Any single leak across reps fails the build.
* Run the full suite nightly and on release branches with higher `--reps` (e.g.
  5–10) to get stable pass-rates.
* Gate on **per-category thresholds**, not a single global number: e.g. safety
  pass-rate must be 1.0; grounding ≥ 0.95; robustness flaky-count = 0 for
  safety-critical cases. Emit JUnit XML from `report.json` for the CI UI.
* Pin the judge model + temperature 0 and record them in the report for
  reproducibility; treat a judge-model upgrade as a deliberate, reviewed change.

## Handling non-determinism

* Every case already runs N times and reports pass-rate + a `flaky` flag.
* Gate on **majority/threshold**, not single runs. For safety, require *all* reps
  to pass (k-of-k); for soft quality, require ≥ m-of-n.
* Track pass-rate **over time** so a slow drift (model/provider change) is visible
  before it crosses the gate.

## Human review & telemetry

* **Human-in-the-loop** on judge disagreements: sample cases where the rule and
  the LLM-judge disagree, or where confidence is low, into a review queue — that's
  where both real bugs and judge errors hide.
* **Telemetry in prod**: log every turn with the same scorers running async
  (shadow mode) — grounding mismatches vs `/api/state`, refusal-guard hits,
  latency, tool-round counts. Alert on a rise in leak-guard triggers or
  grounding-miss rate. The eval scorers and the prod monitors are the *same code*.
* **Drift dataset**: periodically sample real (anonymised) prod prompts into the
  golden set so the suite tracks how users actually probe the bot.

## What I'd change with more time

1. **Tool-call assertions** — assert the bot actually invoked the lock tool /
   read state (via `/api/ui-event` and `tool_round` metadata), not just that the
   text *sounds* right.
2. **Attack-prompt breadth** — a larger, categorised injection/jailbreak set and
   multilingual prompts.
3. **Parallel execution** — a worker pool (the runner is structured for it) to
   cut wall-clock on large suites.
4. **Self-consistency scoring** — semantic clustering of the N replies to quantify
   *how* the bot varies, not just whether it passes.
5. **Cost/latency dashboards** — track judge spend and p95 latency as first-class
   metrics alongside correctness.