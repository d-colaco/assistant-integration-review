"""Run every control against both targets and write the rubric: pass or fail per control, with the test that is
its evidence. There is no total score on purpose: one number is easy to game and invites argument."""

from __future__ import annotations

import asyncio
from datetime import date

from dclabagent.checks import CONTROLS, Finding
from dclabagent.world import TARGETS, open_world


async def run_control(control_id: str, target: str) -> Finding:
    control = next(c for c in CONTROLS if c.id == control_id)
    async with open_world(target) as world:
        return await control.check(world)


def run_all() -> dict[str, dict[str, Finding]]:
    async def go() -> dict[str, dict[str, Finding]]:
        return {c.id: {t: await run_control(c.id, t) for t in TARGETS} for c in CONTROLS}

    return asyncio.run(go())


def render(results: dict[str, dict[str, Finding]]) -> str:
    mark = {True: "pass", False: "FAIL"}
    lines = [
        "# Assistant-integration rubric",
        "",
        f"Generated {date.today().isoformat()} by `make rubric`. Pass or fail per control, each with the test that is its evidence.",
        "The lab rates only its own two servers; there is no total score.",
        "",
        "| Control | Weak | Hardened | Evidence |",
        "|---|---|---|---|",
    ]
    for control in CONTROLS:
        row = results[control.id]
        lines.append(
            f"| {control.title} | {mark[row['weak'].passed]} | {mark[row['hardened'].passed]} | "
            f"`tests/test_rubric.py::test_control[{control.id}-weak]` / `[{control.id}-hardened]` |"
        )
    lines += ["", "## What each run observed", ""]
    for control in CONTROLS:
        lines.append(f"### {control.title}")
        for target in TARGETS:
            finding = results[control.id][target]
            lines.append(f"- **{target}** ({mark[finding.passed]}): {finding.evidence}")
        lines.append("")
    return "\n".join(lines)
