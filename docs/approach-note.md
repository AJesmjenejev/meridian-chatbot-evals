# Approach note

## Bottom line (what I concluded about this chatbot)

**Safe, but not yet grounded.** It reliably refuses secrets and resists prompt
injection (it never leaked a PIN or full card number across the suite), but it is
**not trustworthy for facts**: it confabulates service-fee amounts, over-promises
product eligibility (offers Premium-only products to a Standard customer), and
serves **stale state after an action** (says the card is "active" right after it
was locked). Its variance is concentrated on **adversarial** prompts — the worst
place to be non-deterministic. A nuance worth flagging: where the app's own
dashboards are stale, the bot is often *more* correct than the UI. Everything
below is the method and the evidence behind that one paragraph.

## How I framed the problem

The thing under test is a **non-deterministic, tool-using LLM assistant** sitting
on top of a real banking data model. So I did not treat this as "find bugs in a
feature"; I treated it as **characterising a probabilistic system against a
ground-truth oracle**. The questions I wanted evidence for, before trusting it in
production, were:

1. **Is it grounded?** When it states a fact (balance, IBAN, limit, a product
   price), does it match the real account state — or does it confabulate?
2. **Is it safe?** Does it reliably refuse the things the bank says it must never
   do (reveal a PIN, show a full card number, leak another customer's data,
   obey injected instructions)?
3. **Does it know what it doesn't know?** Asked about a branch/product/transaction
   that doesn't exist, does it decline or invent plausible detail?
4. **Is it stable?** The same prompt twice — same verdict? Variance is itself a
   test result, not noise to average away.

## What a "test case" is here

A test case is a **labelled prompt + an expectation + a way to grade it +
rationale**, run **N times**. Because the model is stochastic, a single pass is
not evidence; a case has a **pass-rate**, and a case that is sometimes-right is a
*finding* (flaky), not a pass. Expectations come in two flavours:

* **Oracle-checkable** — graded by a rule against `GET /api/state` (the source of
  truth). Deterministic, free, fast. Used for balances, limits, BIC, etc.
* **Judgment-checkable** — graded by an LLM-as-judge via `POST /api/llm` (correct‑
  ness, grounding/contradiction, refusal-appropriateness, context retention).
  Used where wording varies but meaning matters. The judge's reliability, scoring
  rationale, failure modes and calibration plan are in
  [`judge-methodology.md`](judge-methodology.md).

Most cases stack **both** a rule and a judge, plus an always-on `no_secret_leak`
guard, so a single scorer can't wave through a leak.

## What I deliberately covered

Grounding, numeric aggregation, card actions (lock/unlock + state-aware status),
PIN/PAN refusal, prompt injection & system-prompt exfiltration, cross-customer
access, out-of-scope deflection, hallucination on non-existent
branches/products/fees/transactions, tier-based eligibility, multi-turn context,
and same-prompt consistency. Ground truth is read **live** from the oracle, never
hard-coded, because the profile is dynamic (the "receive salary" action moves the
balance).

## What I consciously descoped

* **Exhaustive transaction maths** — categorisation is ambiguous (is "Mjam Market
  / Convenience store" groceries?), so I kept one concrete-period aggregation and
  judged it loosely rather than asserting an exact cent figure.
* **Throughput / load testing** — single-user correctness first; I note where
  latency budgets and concurrency would slot in (see scaling note).
* **Full multilingual / accessibility / UI testing** — the brief is about the
  chatbot, so I tested the chat API surface, not the DOM.
* **Jailbreak breadth** — I included representative injection vectors, not an
  exhaustive adversarial corpus; the harness makes adding more a one-line YAML
  change.

## The one design decision that mattered most

**Oracle-first, templated expectations.** Hard-coding "€2,668.83" would have made
the suite lie the moment salary was received. Reading the balance from
`/api/state` at run time (`{{ accounts.0.balance_cents | euros }}`) is what let
the suite stay correct *and* is exactly what surfaced the headline finding: the
assistant keeps reporting the seed balance while the real account state has moved
on (see execution results).