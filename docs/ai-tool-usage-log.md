# AI-tool usage log

**Tools used:** Claude Code (Anthropic agentic CLI) for exploration, harness code,
and dataset authoring; the app's own `POST /api/llm` (Cloudflare Workers AI,
`@cf/nvidia/nemotron-3-120b-a12b`) as the LLM-as-judge inside the harness.

| What | Tool | How I verified the output |
|---|---|---|
| Reverse-engineering the API contract (`/api/redeem`, `/api/chat` SSE, `/api/state`, `/api/llm`, `/api/ui-event`) | Claude Code + `curl` | Read the app's own `app.js` to confirm payload shapes; smoke-tested each endpoint live and diffed replies against the rendered UI. |
| Harness code (client, scorers, runner, report) | Claude Code | Ran `--smoke` + a single-suite run; read `report.json` reply-by-reply to confirm scorers fired correctly before trusting aggregates. |
| Test-case authoring | Claude Code, from the live data | Cross-checked every expected value against `GET /api/state` and the rendered pages (balance, IBAN, BIC, limits, branches, insurance prices). |
| Grading replies (in-harness judge) | `/api/llm` | Did **not** take judge scores on faith: spot-checked judge `reasoning` strings, and caught two judge/test-design issues this way (see below). |

## Where AI was wrong, and how I caught it

* The LLM-judge initially flagged a **correct** "most recent transaction" reply as
  a *hallucination* simply for adding accurate extra detail. Reading the judge's
  `reasoning` exposed it; I rewrote the grounding prompt to penalise only
  **contradictions/fabrications**, not elaboration.
* I initially treated the "Meridian ISA" as a hallucinated product (it's
  suggested in the UI but I'd only seen Wealth/Insurance). Reading the app's
  `app.js` (`PRODUCT_META`) proved the **ISA is real** — my finding was wrong. Fix:
  verify "doesn't-exist" claims against `/api/catalogues/*` / source, never the
  rendered HTML; the ISA became a grounding case, and the genuine defect is the
  bot over-stating ISA *eligibility* (it's Premium-only).
* I harvested fee amounts from the *bot* as provisional ground truth, then
  cross-checked against the UI Service-fees panel — the bot was wrong on three of
  five (overdraft, replacement, expedited). Anchored the dataset to the UI values.
* The first full run showed `no_secret_leak` at 0.975, implying a PIN/PAN leak.
  Reading the two failing replies showed they were **false positives** — the bot
  quoted a counterparty **IBAN**, whose 14-digit run my PAN regex flagged. Fixed
  the guard to strip IBAN-formatted tokens first (verified a real 16-digit PAN and
  a PIN still trip it). The "never leaked a secret" conclusion held; the *scorer*
  was wrong, and reading the evidence rather than the aggregate caught it.
* My first grocery-spend case asserted "~€312" (taken from the UI insight card).
  The bot answered "€0 this month", which is actually **correct** (today is June;
  groceries were in April). The harness output made it obvious the *expectation*
  was wrong, not the bot — I split it into a concrete-April case and a correct
  empty-period June case.

## Verification principle

AI generated the scaffolding fast, but every number in the datasets is anchored to
an **independent oracle** (`/api/state` / the rendered app), and every judge
verdict is auditable via its stored `reasoning`. Rule-based scorers (deterministic)
backstop the probabilistic judge so no single AI component is trusted alone.