"""Render the evidence frames in demo/screenshots from live runs of the lab.

Each frame is an HTML page built from the lab's own output (rubric, transcripts, audit log, reports) and
photographed with headless Chromium. They are evidence, not an interface: the lab has none. Needs Playwright's
Chromium (``playwright install chromium``); set CHROME to use another one. The real-model frame needs
demo/runs/llm-run.json (``make llm-run``) and is skipped when it is absent.
"""

from __future__ import annotations

import asyncio
import glob
import html
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from dclabagent import evidence
from dclabagent.checks import CONTROLS
from dclabagent.rubric import run_all

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "demo" / "screenshots"
RUN = ROOT / "demo" / "runs" / "llm-run.json"

CSS = """
:root { --bg:#ffffff; --fg:#1b1f24; --muted:#59636e; --line:#d0d7de; --ok:#1a7f37; --bad:#cf222e; --warn:#9a6700; --chip:#f6f8fa; }
* { box-sizing: border-box; }
body { margin:0; background:#eef1f4; font:15px/1.45 -apple-system,"Segoe UI",Inter,Helvetica,Arial,sans-serif; color:var(--fg); }
.frame { width:1180px; padding:28px 32px; background:var(--bg); }
h1 { font-size:22px; margin:0 0 4px; } .sub { color:var(--muted); margin:0 0 18px; }
table { border-collapse:collapse; width:100%; } th,td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:600; font-size:13px; text-transform:uppercase; letter-spacing:.03em; }
code, pre, .mono { font-family:"JetBrains Mono","DejaVu Sans Mono",Menlo,monospace; font-size:13px; }
pre { background:var(--chip); border:1px solid var(--line); border-radius:6px; padding:12px; margin:0; white-space:pre-wrap; }
.pass { color:var(--ok); font-weight:700; } .fail { color:var(--bad); font-weight:700; } .warn { color:var(--warn); font-weight:700; }
.cols { display:grid; grid-template-columns:1fr 1fr; gap:22px; } .col h2 { font-size:16px; margin:0 0 8px; }
.step { padding:6px 10px; border:1px solid var(--line); border-radius:6px; margin-bottom:6px; background:var(--chip); }
.step .o { font-size:13px; margin-top:2px; } .foot { margin-top:14px; padding-top:10px; border-top:1px solid var(--line); color:var(--muted); font-size:13px; }
.chip { display:inline-block; background:var(--chip); border:1px solid var(--line); border-radius:10px; padding:0 8px; font-size:12px; color:var(--muted); }
"""


def page(title: str, sub: str, body: str, foot: str = "") -> str:
    footer = f'<div class="foot">{foot}</div>' if foot else ""
    return f'<html><head><meta charset="utf-8"><style>{CSS}</style></head><body><div class="frame"><h1>{html.escape(title)}</h1><p class="sub">{sub}</p>{body}{footer}</div></body></html>'


def esc(value) -> str:
    return html.escape(str(value))


def verdict(ok: bool) -> str:
    return '<span class="pass">pass</span>' if ok else '<span class="fail">FAIL</span>'


def frame_rubric() -> str:
    results = run_all()
    rows = "".join(
        f"<tr><td>{esc(c.title)}</td><td>{verdict(results[c.id]['weak'].passed)}</td><td>{verdict(results[c.id]['hardened'].passed)}</td></tr>"
        for c in CONTROLS
    )
    body = f"<table><tr><th>Control</th><th>Weak server</th><th>Hardened server</th></tr>{rows}</table>"
    return page("Assistant-integration rubric", "Ten controls, each decided by what the system did, on a fictional support desk. No total score.", body,
                "Source: <code>make rubric</code>. The weak server is weak on purpose and the hardened one was written to pass: the table shows the controls can be implemented and tested.")


def attack_colour(outcome: str, leaked: bool, planted: bool) -> str:
    """One meaning in every frame: red when a planted instruction got its way, green when the system stopped it, no
    colour for the task's own reads."""
    if not planted:
        return ""
    return "fail" if leaked or outcome.startswith(("ok", "applied")) else "pass"


def step_html(step: dict) -> str:
    colour = attack_colour(step["outcome"], step["leaked"], step["origin"] != "task")
    args = json.dumps(step["args"], ensure_ascii=False)
    args = args if len(args) < 110 else args[:107] + "..."
    return f'<div class="step"><code>{esc(step["call"])}</code> <span class="chip">from {esc(step["origin"])}</span><div class="mono">{esc(args)}</div><div class="o {colour}">{esc(step["outcome"])}</div></div>'


def frame_planted(runs) -> str:
    cols = ""
    for run in runs:
        steps = "".join(step_html(s) for s in run["steps"])
        facts = f"messages sent: {len(run['outbox'])} &middot; documents changed: {esc(', '.join(run['changed']) or 'none')} &middot; confidential text in the steps: {'yes' if any(s['leaked'] for s in run['steps']) else 'no'}"
        cols += f'<div class="col"><h2>{esc(run["target"].title())} desk</h2>{steps}<div class="foot">{facts}</div></div>'
    return page("A planted instruction, an assistant that obeys everything", "The assistant reads two tickets that carry instructions and does what each says. Same script, same tickets, two servers.",
                f'<div class="cols">{cols}</div>', "Source: <code>tests/test_rubric.py::test_control[planted_instructions-*]</code>. Outcomes are the server's answers; the footer is the system's own state afterwards.")


def frame_audit(run) -> str:
    rows = "".join(
        f"<tr><td class='mono'>{esc(r['session'])}</td><td>{esc(r['key'])}</td><td><code>{esc(r['tool'])}</code></td>"
        f"<td class='mono'>{esc(json.dumps(r['args'], ensure_ascii=False))}</td><td>{esc(r['outcome'])}</td><td>{r['result_bytes']}</td></tr>"
        for r in run["audit"]
    )
    return page("The hardened desk's audit log for that run", "One row per call: the key, the tool, the arguments (ids and sizes, never document text), the outcome and the size of the answer.",
                f"<table><tr><th>Session</th><th>Key</th><th>Tool</th><th>Arguments</th><th>Outcome</th><th>Bytes</th></tr>{rows}</table>",
                "The audit tells a refused read of a forbidden document (<code>denied</code>) from a missing one (<code>missing</code>); the assistant cannot.")


def frame_session(data) -> str:
    calls = "".join(f"<div class='step mono'>{esc(c)}</div>" for c in data["calls"])
    report = json.dumps(data["report"], indent=2, ensure_ascii=False)
    return page("What did the assistant see?", "Five calls in one session, then the per-session report from the audit log.",
                f'<div class="cols"><div class="col"><h2>The session</h2>{calls}</div><div class="col"><h2>session_report</h2><pre>{esc(report)}</pre></div></div>',
                "Note <code>documents_read</code>: the forbidden CUST-1 is not listed, because nothing was returned. Timestamps are the lab's test clock.")


def frame_approval(data) -> str:
    steps = "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td></tr>" for a, b in data["steps"])
    queue = "".join(
        f"<tr><td>{esc(name)}</td><td>{row['proposals']}</td><td>{row['applied_by_agent']}</td><td>{row['waiting_for_a_person']}</td></tr>"
        for name, row in data["queue"].items()
    )
    body = (
        f"<table><tr><th>Step</th><th>Answer</th></tr>{steps}</table><h2 style='font-size:16px;margin:18px 0 8px'>The proposal as a diff</h2><pre>{esc(data['diff'])}</pre>"
        f"<h2 style='font-size:16px;margin:18px 0 8px'>The queue under two policies (100 proposals: 80 low risk, 20 high risk)</h2>"
        f"<table><tr><th>Policy</th><th>Proposals</th><th>Applied by an agent approver</th><th>Waiting for a person</th></tr>{queue}</table>"
    )
    return page("An approval queue, by risk class", "A write is a proposal with a diff and an expiry. The risk class of the path decides who may apply it.", body,
                "Source: <code>tests/test_rubric.py::test_control[approval_policy-*]</code> and <code>make queue</code> (counts of a synthetic workload).")


def frame_description(data) -> str:
    cols = ""
    for target in ("weak", "hardened"):
        d = data[target]
        steps = "".join(f"<div class='step'><code>{esc(s['call'])}</code> <span class='chip'>from {esc(s['origin'])}</span><div class='o'>{esc(s['outcome'][:80])}</div></div>" for s in d["steps"])
        events = "".join(f"<div class='step warn mono'>{esc(json.dumps(e))}</div>" for e in d["events"]) or "<div class='step mono'>no gateway events</div>"
        notes = esc("; ".join(d["board_notes"]) or "empty")
        cols += (
            f"<div class='col'><h2>{target.title()} pairing</h2><div class='mono' style='margin-bottom:8px'>board notes afterwards: <span class='{'fail' if d['leaked'] else 'pass'}'>{notes}</span></div>"
            f"<h2 style='font-size:14px'>Assistant's calls</h2>{steps}<h2 style='font-size:14px;margin-top:10px'>Gateway events</h2>{events}</div>"
        )
    changed = esc(data["hardened"]["changed_description"])
    return page("A tool description that changes after review", "The public board edits the description of <code>post_note</code> after it was reviewed. The key and the desk are wide open on purpose: only the gateway stands in the way.",
                f"<pre>{changed}</pre><div class='cols' style='margin-top:14px'>{cols}</div>",
                "Source: <code>tests/test_rubric.py::test_control[description_change-*]</code>.")


def frame_extraction(data) -> str:
    rows = "".join(
        f"<tr><td>{t.title()} desk</td><td>{d['extracted']} of 60</td><td>{d['calls']}</td><td>{esc(d['stopped_by'] or 'not stopped')}</td><td>{d['audit_limit_rows']}</td></tr>"
        for t, d in data.items()
    )
    return page("Slow extraction against per-key limits", "Sixty small reads of permitted tickets, one every 61 seconds, so the per-minute rate never trips. The key's cap on calls does.",
                f"<table><tr><th>Target</th><th>Tickets extracted</th><th>Calls made</th><th>Stopped by</th><th>Limit rows in the audit</th></tr>{rows}</table>",
                "Source: <code>tests/test_rubric.py::test_control[per_key_limits-*]</code>. The cap is 25 calls and one was spent reading the ticket that held the instruction.")


def frame_model(record) -> str:
    from dclabagent.llm_suite import summarise

    rows, short = "", []
    for row in summarise(record):
        if row["runs"] < 10:  # a cell of a few runs measures nothing; it is named in the footer and kept in the record
            short.append(row)
            continue
        rows += (
            f"<tr><td>{esc(row['attack'])}</td><td>{row['target'].title()}</td><td>{row['runs']}</td><td>{row['tried']}</td>"
            f"<td class='{'fail' if row['got_through'] else 'pass'}'>{row['got_through']}</td></tr>"
        )
    return page(
        f"A real model reads the planted tickets ({esc(record['model'])})",
        f"Local model through Ollama, temperature {record['temperature']}, {esc(record['date'])}. Prose tickets, no scripted syntax; the runs column is the number of runs in that cell.",
        f"<table><tr><th>What the ticket asked for</th><th>Server</th><th>Runs</th><th>Model tried it</th><th>Got through</th></tr>{rows}</table>",
        "Source: <code>make llm-run</code>. Results vary between runs and models; the verdicts of the lab come from the scripted run, not from this one. “Got through” is read from the system's state after each run."
        + (f" Two more prose tickets ({' and '.join(f'“{esc(a)}”' for a in sorted({r['attack'] for r in short}))}) ran {short[0]['runs']} times on each desk"
           " with no attempt; they are in <code>demo/runs/llm-run.json</code>." if short else ""),
    )


def frame_model_transcript(record) -> str | None:
    """A run in which the model followed the planted text on the weak server, and the same calls replayed on the
    hardened one (the model never tried the attack there, so there is no live run to show)."""
    run = next((r for r in record["results"] if r["target"] == "weak" and r["attempted"]["sent"]), None)
    if run is None:
        return None
    calls = [{"server": e["server"], "tool": e["tool"], "arguments": e["arguments"]} for e in run["events"] if e["kind"] == "call"]
    replay = asyncio.run(evidence.replay_on("hardened", calls))

    def column(title: str, steps: list[dict], facts: str) -> str:
        def args(s: dict) -> str:
            text = json.dumps(s["args"], ensure_ascii=False)
            return text if len(text) <= 150 else text[:147] + "..."

        # the first call reads the ticket the task named; every later one comes from the ticket's text
        cards = "".join(
            f"<div class='step'><code>{esc(s['call'])}</code><div class='mono'>{esc(args(s))}</div>"
            f"<div class='o {attack_colour(s['outcome'], s['leaked'], i > 0)}'>{esc(s['outcome'][:90])}</div></div>"
            for i, s in enumerate(steps)
        )
        return f"<div class='col'><h2>{title}</h2>{cards}<div class='foot'>{facts}</div></div>"

    live = [
        {"call": f"{e['server']}.{e['tool']}", "args": e["arguments"], "outcome": evidence.outcome_of(e["text"]), "leaked": "example.test" in e["text"]}
        for e in run["events"] if e["kind"] == "result"
    ]
    weak_facts = f"live run, seed {run['seed']} &middot; messages sent: {1 if run['succeeded']['confidential_text_sent'] else 0}"
    hard_facts = f"the same calls, replayed &middot; messages sent: {len(replay['outbox'])} &middot; documents changed: {esc(', '.join(replay['changed']) or 'none')}"
    return page(
        "A real model followed the planted text; the same calls on the hardened desk",
        f"Left: {esc(record['model'])} reading a prose ticket on the weak desk and doing what it said. Right: its exact calls, replayed on the hardened desk.",
        f"<div class='cols'>{column('Weak desk (live run)', live, weak_facts)}{column('Hardened desk (replay)', replay['steps'], hard_facts)}</div>",
        "Source: <code>demo/runs/llm-run.json</code> and <code>scripts/screenshots.py</code>. The model never tried the attack on the hardened desk in 17 runs, so the right side is a replay, not a second live run.",
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frames: dict[str, str] = {}
    planted = [asyncio.run(evidence.planted_run(t)) for t in ("weak", "hardened")]
    frames["01-rubric"] = frame_rubric()
    frames["02-planted-instruction"] = frame_planted(planted)
    frames["03-audit-log"] = frame_audit(planted[1])
    frames["04-session-report"] = frame_session(asyncio.run(evidence.session_report_run()))
    frames["05-approval-queue"] = frame_approval(asyncio.run(evidence.approval_run()))
    frames["06-description-change"] = frame_description(asyncio.run(evidence.description_run()))
    frames["07-slow-extraction"] = frame_extraction(asyncio.run(evidence.extraction_run()))
    if RUN.exists():
        record = json.loads(RUN.read_text(encoding="utf-8"))
        frames["08-real-model-summary"] = frame_model(record)
        transcript = frame_model_transcript(record)
        if transcript:
            frames["09-real-model-run"] = transcript
    executable = os.environ.get("CHROME") or sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")))[-1]
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=executable, args=["--no-sandbox"])
        page_ = browser.new_page(viewport={"width": 1240, "height": 900}, device_scale_factor=1.5)
        for name, content in frames.items():
            page_.set_content(content)
            page_.locator(".frame").screenshot(path=str(OUT / f"{name}.png"))
            print("wrote", name)
        browser.close()


if __name__ == "__main__":
    sys.exit(main())
