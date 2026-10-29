"""The approval queue under two policies, on the same workload.

Workload: 100 proposals an assistant makes in a working day, 80 to a low-risk path (runbooks) and 20 to a high-risk
one (policies). Policy A has no agent approver, so every proposal waits for a person. Policy B has an agent approver
that may apply low-risk proposals made by another key; the high-risk ones still wait for a person. The figures are
counts from this synthetic workload, not a forecast of anyone's real queue.
"""

from __future__ import annotations

from dclabagent.hardened import HardenedDesk

LOW, HIGH = 80, 20


def _run(with_agent_approver: bool) -> dict[str, int]:
    desk = HardenedDesk(clock=lambda: 1_000_000.0)
    writer = desk.issue_key("sam", collections={"runbooks"}, ceiling="T1", grants={"propose"})
    policy_writer = desk.issue_key("sam", collections={"policies"}, ceiling="T1", grants={"propose"})
    approver = desk.issue_key("sam", collections={"runbooks", "policies"}, ceiling="T1", grants={"approve"})
    proposals = [desk.propose_change(writer, "q", "RB-1", f"low {i}", "q")["proposal"] for i in range(LOW)]
    proposals += [desk.propose_change(policy_writer, "q", "POL-1", f"high {i}", "q")["proposal"] for i in range(HIGH)]
    if with_agent_approver:
        for proposal in proposals:
            desk.approve(approver, "q", proposal)
    pending = sum(1 for p in desk.proposals.values() if p.status == "pending")
    return {"proposals": len(proposals), "applied_by_agent": len(proposals) - pending, "waiting_for_a_person": pending}


def measure() -> dict[str, dict[str, int]]:
    return {"A: every change waits for a person": _run(False), "B: approval by risk class": _run(True)}


def render_queue(results: dict[str, dict[str, int]]) -> str:
    lines = ["| Policy | Proposals | Applied by an agent approver | Waiting for a person |", "|---|---|---|---|"]
    for name, row in results.items():
        lines.append(f"| {name} | {row['proposals']} | {row['applied_by_agent']} | {row['waiting_for_a_person']} |")
    return "\n".join(lines)
