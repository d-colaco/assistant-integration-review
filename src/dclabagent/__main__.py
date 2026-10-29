"""Command line: ``python -m dclabagent rubric|queue|serve``."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dclabagent")
    sub = parser.add_subparsers(dest="command", required=True)
    rubric = sub.add_parser("rubric", help="run the attack suite against both servers and write reports/rubric.md")
    rubric.add_argument("--out", default="reports/rubric.md")
    llm = sub.add_parser("llm-run", help="optional: a real local model reads the prose planted tickets (needs Ollama)")
    llm.add_argument("--runs", type=int, default=3)
    llm.add_argument("--out", default="demo/runs/llm-run.json")
    llm.add_argument("--scenario", action="append", default=[], help="only this scenario (send-out, overwrite, public-post); repeatable")
    llm.add_argument("--first-seed", type=int, default=1)
    llm.add_argument("--append", action="store_true", help="add the runs to the existing record")
    sub.add_parser("queue", help="measure the approval queue under two policies")
    serve = sub.add_parser("serve", help="serve a desk over stdio so a real MCP client can connect")
    serve.add_argument("target", choices=("weak", "hardened"))
    args = parser.parse_args(argv)
    logging.getLogger("mcp").setLevel(logging.WARNING)  # the SDK logs every request at INFO

    if args.command == "rubric":
        from dclabagent.rubric import render, run_all

        text = render(run_all())
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(text)
        return 0
    if args.command == "llm-run":
        from dclabagent.llm_suite import main as llm_main

        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        llm_main(args.runs, args.out, tuple(args.scenario), args.first_seed, args.append)
        return 0
    if args.command == "queue":
        from dclabagent.queue_measure import measure, render_queue

        print(render_queue(measure()))
        return 0
    from dclabagent.serve import serve_stdio

    serve_stdio(args.target, os.environ.get("DESK_KEY"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
