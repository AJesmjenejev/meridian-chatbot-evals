# How to run — manual guide + metadata capture

Two ways to drive this: the **harness** (automated, recommended) and **by hand**
(curl / Python REPL) to poke the API yourself. Plus how to capture a complete
session-metadata snapshot.

---

## 0. Setup (once)

```bash
cd ~/meridian-chatbot-evals
pip install -e .                 # or: uv venv && uv pip install -e .
cp .env.example .env             # set MERIDIAN_BASE_URL + MERIDIAN_TOKEN
```

`MERIDIAN_TOKEN` = the value after `?token=` in your invitation link.
If your network blocks the `GET` calls or its TLS root CA isn't trusted, add
`MERIDIAN_STATE_FILE=captured_state.json` and `MERIDIAN_VERIFY_SSL=false`.

---

## 1. Run the harness (automated)

```bash
python -m meridian_evals --smoke               # connectivity check
python -m meridian_evals datasets/*.yaml       # all 65 cases
python -m meridian_evals datasets/safety.yaml --reps 5   # one suite, more reps
```
Outputs land in `outputs/<timestamp>/` (`report.html`, `report.json`,
`scored.csv`) and `outputs/latest/`.

---

## 2. Run it manually by hand (curl)

The API is 4 POSTs + 2 GETs. `BASE` = your host, `TOK` = your token.

```bash
BASE="https://2ndround.sandb0x.run"; TOK="<your-token>"

# (a) redeem the token -> sessionId  (safe to repeat)
SID=$(curl -s -X POST "$BASE/api/redeem" -H 'content-type: application/json' \
       -d "{\"token\":\"$TOK\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)['sessionId'])")
echo "session=$SID"

# (b) fetch full state (the ground-truth oracle)
curl -s "$BASE/api/state?session=$SID" -H 'accept: application/json' | python3 -m json.tool

# (c) chat — SSE stream (tool_round / chunk / done frames)
curl -sN -X POST "$BASE/api/chat" \
     -H 'content-type: application/json' -H 'accept: text/event-stream' \
     -d "{\"sessionId\":\"$SID\",\"message\":\"What is my balance?\",\"threadId\":null}"

# (d) LLM pass-through (used for LLM-as-judge) — returns text + reasoning_trace
curl -s -X POST "$BASE/api/llm" -H 'content-type: application/json' \
     -d "{\"sessionId\":\"$SID\",\"system\":\"You are a grader. Output only JSON.\",\"user\":\"Return {\\\"ok\\\":1}\"}"

# (e) UI action (simulate something in the app) — response carries the new state
curl -s -X POST "$BASE/api/ui-event" -H 'content-type: application/json' \
     -d "{\"sessionId\":\"$SID\",\"kind\":\"card_lock\",\"payload\":{\"card_id\":\"card_debit_01\"}}"

# (f) conversation history (the server-side recording of your session)
curl -s "$BASE/api/threads?session=$SID" | python3 -m json.tool          # list threads
curl -s "$BASE/api/threads/<threadId>?session=$SID" | python3 -m json.tool # full turns

# (g) catalogues (products / fees / limits)
curl -s "$BASE/api/catalogues/fee_schedule?session=$SID" | python3 -m json.tool
curl -s "$BASE/api/catalogues/policy_map?session=$SID"   | python3 -m json.tool
curl -s "$BASE/api/catalogues/feature_map?session=$SID"  | python3 -m json.tool
```

API contract reference:

| Endpoint | Method | Body | Returns |
|---|---|---|---|
| `/api/redeem` | POST | `{token}` | `{ok, sessionId}` |
| `/api/state` | GET | `?session=SID` | `{state:{accounts,cards,transactions,customer,ui,…}}` |
| `/api/chat` | POST | `{sessionId,message,threadId}` (Accept SSE) | SSE `tool_round`/`chunk{text}`/`done{turn,threadId}`/`error` |
| `/api/llm` | POST | `{sessionId,user,system?}` | `{ok,text,latency_ms,reasoning_trace}` |
| `/api/ui-event` | POST | `{sessionId,kind,payload}` | `{ok,state,event}` |
| `/api/catalogues/{fee_schedule\|feature_map\|policy_map}` | GET | `?session=SID` | `{value:{…}}` |

UI-event `kind`s: `card_lock`, `card_unlock`, `card_control_toggle {control,enabled}`,
`limit_update {limit_id,value_cents}`, `payment_make {account_id,amount_cents,beneficiary_name,iban}`,
`transfer_incoming {account_id,amount_cents,source}`.

---

## 3. Run it manually by hand (Python REPL)

```python
import os
from meridian_evals.client import MeridianClient
c = MeridianClient(os.environ["MERIDIAN_BASE_URL"], os.environ["MERIDIAN_TOKEN"],
                   verify_ssl=False)
c.redeem()
print(c.get_state()["accounts"][0]["balance_cents"])
r = c.chat("How much is the replacement card fee?")
print(r.text, r.tool_rounds, r.latency_ms)
print(c.llm(user="grade ...", system="output JSON only"))
c.ui_event("card_lock", {"card_id": "card_debit_01"})   # simulate an action
```

---

## 4. Get complete metadata (one snapshot)

```bash
python scripts/capture_metadata.py
#   → metadata_<ts>.json  with: sessionId, full state, all 3 catalogues,
#     a sample chat turn (raw SSE events + tool_rounds + latency + threadId),
#     and a sample /api/llm call (text + reasoning_trace + latency).
python scripts/capture_metadata.py --probe "Lock my card"   # custom probe
```

This is the easiest way to grab the authoritative oracle + the chat/LLM response
metadata for the write-up. (You can also re-use `captured_state.json` /
`captured_catalogues.json` already in the repo as offline fallbacks.)

---

## 5. Offline mock layer (no token / CI / scorer tests)

A second layer replays a **cassette** (synthetic API state + canned chat replies)
with zero network — for reviewers without a token, CI, and testing the scorers
deterministically.

```bash
# Hand-authored demo: edit fixtures/demo_cassette.json then re-run to flip results
python -m meridian_evals --mock fixtures/demo_cassette.json fixtures/mock_demo.yaml
#   → 3 pass, 1 fails on purpose (secret-leak guard catches a planted PAN)

# Record a REAL cassette during a live run, then replay it forever offline:
python -m meridian_evals datasets/*.yaml --record fixtures/run.json     # live + save
python -m meridian_evals datasets/*.yaml --mock fixtures/run.json       # offline replay
```

* The hand-authored cassette (`fixtures/demo_cassette.json`) lets you **change the
  mocked API** (balance, a fee reply, lock state) and **assert the expected chat
  answer** — i.e. test the harness/scorers without the live LLM.
* A `--record` cassette replays the real chat replies *and* the real LLM-judge
  verdicts, so `--mock` reproduces the exact scored run offline. Recorded chat
  variance (multiple replies per prompt) is preserved across reps.

## 6. Simulate actions, then eval (stale-context flow)

Cases in `datasets/stale_context.yaml` declare reversible UI actions; the runner:

1. runs `setup_actions` via `/api/ui-event` (e.g. lock the card),
2. takes the **new state from that response** as the oracle,
3. asks the bot and scores the reply against that post-action state,
4. runs `teardown_actions` to restore the session (unlock / reset).

Run just those:
```bash
python -m meridian_evals datasets/stale_context.yaml
```
Add your own by copying a case and changing `setup_actions` / `user_input` /
`teardown_actions` — payload values may use `{{ oracle.path }}` templating
(e.g. `card_id: "{{ cards.0.id }}"`).
```