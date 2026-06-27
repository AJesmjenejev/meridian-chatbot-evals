"""Reporting: console summary + JSON + CSV + a single-file HTML report."""

from __future__ import annotations

import csv
import datetime as _dt
import html
import json
import statistics
from pathlib import Path
from typing import Any

from .models import RepResult
from .runner import consistency


def _agg_by_category(results: list[RepResult]) -> dict[str, dict[str, Any]]:
    by_cat: dict[str, list[RepResult]] = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r)
    out = {}
    for cat, reps in by_cat.items():
        verdicts = [r.rep_passed for r in reps if r.rep_passed is not None]
        passes = sum(1 for v in verdicts if v)
        out[cat] = {
            "reps_scored": len(verdicts),
            "reps_passed": passes,
            "pass_rate": round(passes / len(verdicts), 3) if verdicts else None,
        }
    return out


def _scorer_breakdown(results: list[RepResult]) -> dict[str, dict[str, Any]]:
    by_scorer: dict[str, list[float]] = {}
    for r in results:
        for name, s in r.scores.items():
            if s.score is not None:
                by_scorer.setdefault(name, []).append(s.score)
    return {
        name: {"n": len(v), "mean_score": round(statistics.mean(v), 3)}
        for name, v in sorted(by_scorer.items())
    }


def summarize(results: list[RepResult]) -> dict[str, Any]:
    cons = consistency(results)
    return {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "total_cases": len({r.case_id for r in results}),
        "total_reps": len(results),
        "by_category": _agg_by_category(results),
        "by_scorer": _scorer_breakdown(results),
        "consistency": cons,
        "flaky_cases": [cid for cid, c in cons.items() if c["flaky"]],
        "errors": [
            {"case_id": r.case_id, "rep": r.rep, "error": r.error} for r in results if r.error
        ],
    }


def print_console(summary: dict[str, Any]) -> None:
    print("\n" + "=" * 64)
    print(f"  MERIDIAN CHATBOT EVALS — {summary['generated_at']}")
    print(f"  {summary['total_cases']} cases · {summary['total_reps']} reps")
    print("=" * 64)
    print("\n  Pass-rate by category")
    for cat, a in sorted(summary["by_category"].items()):
        pr = a["pass_rate"]
        bar = "█" * int((pr or 0) * 20)
        print(f"    {cat:<16} {str(pr):<6} {bar}  ({a['reps_passed']}/{a['reps_scored']})")
    print("\n  Mean score by scorer")
    for name, a in summary["by_scorer"].items():
        print(f"    {name:<34} {a['mean_score']:<6} (n={a['n']})")
    if summary["flaky_cases"]:
        print("\n  ⚠ Flaky (non-deterministic) cases:")
        for cid in summary["flaky_cases"]:
            c = summary["consistency"][cid]
            print(f"    {cid:<24} pass_rate={c['pass_rate']}")
    if summary["errors"]:
        print(f"\n  ✖ {len(summary['errors'])} reply error(s) — see report.json")
    print()


def write_reports(results: list[RepResult], out_root: str = "outputs") -> Path:
    ts = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out = Path(out_root) / ts
    out.mkdir(parents=True, exist_ok=True)
    summary = summarize(results)

    (out / "report.json").write_text(
        json.dumps(
            {"summary": summary, "rows": [_row_dict(r) for r in results]},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_csv(results, out / "scored.csv")
    (out / "report.html").write_text(_render_html(summary, results), encoding="utf-8")

    latest = Path(out_root) / "latest"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(out.name)
    except OSError:
        pass
    return out


def _row_dict(r: RepResult) -> dict[str, Any]:
    return {
        "case_id": r.case_id,
        "category": r.category,
        "rep": r.rep,
        "prompt": r.prompt,
        "reply": r.reply,
        "latency_ms": round(r.latency_ms, 1),
        "tool_rounds": r.tool_rounds,
        "error": r.error,
        "rep_passed": r.rep_passed,
        "scores": {
            n: {"score": s.score, "label": s.label, "reasoning": s.reasoning}
            for n, s in r.scores.items()
        },
    }


def _write_csv(results: list[RepResult], path: Path) -> None:
    scorer_names = sorted({n for r in results for n in r.scores})
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["case_id", "category", "rep", "prompt", "reply", "latency_ms", "rep_passed"]
            + scorer_names
        )
        for r in results:
            w.writerow(
                [
                    r.case_id,
                    r.category,
                    r.rep,
                    r.prompt,
                    r.reply,
                    round(r.latency_ms, 1),
                    r.rep_passed,
                ]
                + ["" if r.scores.get(n) is None else r.scores[n].score for n in scorer_names]
            )


def _score_cell(r: RepResult, esc: Any) -> str:
    """Render the per-scorer breakdown for one detail row."""
    return "<br>".join(
        f"<b>{esc(n)}</b>: {esc(s.score)} "
        f"<span class='lbl'>{esc(s.label or '')}</span> "
        f"<span class='rsn'>{esc(s.reasoning)}</span>"
        for n, s in r.scores.items()
    )


def _render_html(summary: dict[str, Any], results: list[RepResult]) -> str:
    def esc(x: Any) -> str:
        return html.escape(str(x))

    cat_rows = "\n".join(
        f"<tr><td>{esc(c)}</td><td>{esc(a['pass_rate'])}</td>"
        f"<td>{a['reps_passed']}/{a['reps_scored']}</td></tr>"
        for c, a in sorted(summary["by_category"].items())
    )
    scorer_rows = "\n".join(
        f"<tr><td>{esc(n)}</td><td>{esc(a['mean_score'])}</td><td>{a['n']}</td></tr>"
        for n, a in summary["by_scorer"].items()
    )
    detail_rows = "\n".join(
        f"<tr class='{('pass' if r.rep_passed else 'fail' if r.rep_passed is False else 'na')}'>"
        f"<td>{esc(r.case_id)}</td><td>{esc(r.rep)}</td>"
        f"<td>{esc(r.prompt)}</td><td>{esc(r.reply)}</td>"
        f"<td>{round(r.latency_ms)}</td>"
        f"<td>{_score_cell(r, esc)}</td></tr>"
        for r in results
    )
    flaky = ", ".join(summary["flaky_cases"]) or "none"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meridian Chatbot Evals</title>
<style>
body{{font:14px/1.5 system-ui,sans-serif;margin:2rem;color:#1a1a1a}}
h1{{margin:0}} .sub{{color:#666}}
table{{border-collapse:collapse;margin:1rem 0;width:100%}}
th,td{{border:1px solid #ddd;padding:6px 8px;text-align:left;vertical-align:top}}
th{{background:#f4f4f4}}
tr.pass td:first-child{{border-left:4px solid #2e9e44}}
tr.fail td:first-child{{border-left:4px solid #d4351c}}
tr.na td:first-child{{border-left:4px solid #aaa}}
.lbl{{color:#0b5cab}} .rsn{{color:#666;font-size:12px}}
td:nth-child(4){{max-width:380px}}
</style>
</head>
<body>
<h1>Meridian Chatbot Evals</h1>
<div class="sub">{esc(summary["generated_at"])} · {summary["total_cases"]} cases ·
{summary["total_reps"]} reps · flaky: {esc(flaky)}</div>

<h2>Pass-rate by category</h2>
<table>
<thead><tr><th>Category</th><th>Pass rate</th><th>Passed</th></tr></thead>
<tbody>
{cat_rows}
</tbody>
</table>

<h2>Mean score by scorer</h2>
<table>
<thead><tr><th>Scorer</th><th>Mean</th><th>n</th></tr></thead>
<tbody>
{scorer_rows}
</tbody>
</table>

<h2>Per-reply detail</h2>
<table>
<thead><tr><th>Case</th><th>Rep</th><th>Prompt</th><th>Reply</th><th>ms</th><th>Scores</th></tr></thead>
<tbody>
{detail_rows}
</tbody>
</table>
</body>
</html>"""
