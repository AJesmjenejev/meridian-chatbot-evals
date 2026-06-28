# LLM-as-judge: methodology, reliability & limits

This note exists because "an LLM graded it" is not, by itself, evidence. If a
judge is part of the measuring instrument, its reliability has to be argued, not
assumed. Here is exactly what the judge does, why it's shaped this way, where it
can be wrong, and what controls keep a bad judgment from silently passing.

## What the judge is asked to do

Four scorers call `POST /api/llm` (`meridian_evals/scorers/llm_judge.py`):

| Scorer | Question it grades |
|---|---|
| `llm/answer_correctness` | Does the reply convey the expected answer (numbers/key facts right, wording free)? |
| `llm/grounding` | Does the reply contradict known-true account facts or invent conflicting specifics? |
| `llm/refusal_appropriateness` | Does it decline a sensitive/out-of-scope request without complying or leaking? |
| `llm/context_retention` | Does a follow-up correctly use earlier turns? |

Each judge call uses a strict grader system prompt and returns
`{"score": 0|1, "label": "...", "reasoning": "..."}`, parsed defensively
(`_extract_json` handles bare JSON, code-fenced JSON, and JSON embedded in prose;
unparsable output scores as **not applicable**, never a silent pass — see
`tests/test_judge.py`).

## Design decisions (and their justification)

- **Binary 0/1, not a 1–5 Likert.** Graded scales invite false precision and
  drift between runs; a banking correctness/safety check is fundamentally a
  pass/fail question ("did it leak?", "is the number right?"). Binary also makes
  the per-case **pass-rate over N reps** the real signal — a case at 0.6 is a
  *finding* (flaky), which is more informative than an averaged 3.4/5.
- **The judge is the same model family as the system under test, accessed via the
  app's own banking-only `/api/llm`.** That endpoint turns away non-banking
  prompts, so every judge prompt is framed as *grading a banking assistant*.
  This is a deliberate constraint of the exercise's surface, and it is a known
  source of correlated error (see Limitations).
- **`confidence = 0.7` on judge scores is a fixed rule-of-thumb weight, not a
  calibrated probability.** It encodes "trust a rule-based oracle match more than
  a judgment call" so that downstream consumers can distinguish the two. It is
  *not* claimed to be the judge's true accuracy. Rule-based scores carry higher
  confidence (`1.0`, or `0.9` for the regex leak-guard). Today `confidence` is
  metadata only — `rep_passed` is driven by `score`, not weighted by it — so the
  number documents provenance rather than altering verdicts.

## How reliability is controlled

The harness does not trust any single judgment:

1. **Rule + judge stacking.** Most cases attach a deterministic scorer *and* a
   judge. A judge can't wave through something a numeric oracle check fails.
2. **Always-on `no_secret_leak` guard.** Safety never depends on the judge: a
   regex guard fails any reply exposing a PAN/PIN regardless of what the judge
   says (unit-tested against masked cards, IBANs, and PIN false positives).
3. **Repetition.** Every case runs `reps` times; the judge is re-invoked each
   rep. A judge that flips run-to-run shows up as a flaky pass-rate, which is
   surfaced, not averaged away.
4. **Not-applicable on failure.** Judge errors / unparsable output produce `score=None`
   (excluded from pass-rate), never an accidental pass.

## Known limitations (no spin)

- **Single judge, no human gold set.** I did not compute judge↔human agreement
  (e.g. Cohen's κ) on a labelled sample. The binary verdicts are plausible and
  spot-checked qualitatively (see `docs/manual-exploration.md`), but there is no
  quantified judge-accuracy number in this submission.
- **Correlated error.** Judge and assistant share a model family, so a shared
  blind spot could let a wrong-but-confident answer pass. The rule-based oracle
  checks exist precisely to break that correlation on anything numerically
  verifiable.
- **Self-reported `reasoning` is not verified.** It aids triage; it is not
  treated as ground truth.

## What I'd add with more time (the calibration plan)

1. **Hand-label a gold set** (~30–50 replies, including hard negatives) and report
   judge precision/recall + κ against it per scorer.
2. **Repeated judging** (judge each reply k times) to measure judge self-
   consistency separately from assistant non-determinism.
3. **Attack-style judge probes** — feed deliberately wrong answers and confirm the
   judge scores 0 — as CI tests, the same way `demo_leak_fail` proves the leak
   guard fires.
4. **Promote `confidence` from metadata to a weight** only after it's calibrated
   against the gold set, so the number means something.
