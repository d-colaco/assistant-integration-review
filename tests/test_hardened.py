"""The hardened desk's rules one by one, through the same MCP surface the attacks use."""

import asyncio
import json

import pytest

from dclabagent.hardened import HardenedDesk, KeyScopeError, Limits
from dclabagent.queue_measure import measure
from dclabagent.world import open_world


def run(coro):
    return asyncio.run(coro)


def test_a_key_cannot_be_wider_than_its_user_in_collections_or_tier() -> None:
    desk = HardenedDesk()
    with pytest.raises(KeyScopeError):
        desk.issue_key("ola", collections={"faq", "runbooks"})
    with pytest.raises(KeyScopeError):
        desk.issue_key("ola", ceiling="T1")
    with pytest.raises(KeyScopeError):
        desk.issue_key("nobody")
    assert desk.issue_key("sam", collections={"faq"}, ceiling="T0")


def test_an_unknown_key_gets_nothing_and_is_audited() -> None:
    desk = HardenedDesk()
    assert desk.read("hk_unknown", "s1", "FAQ-1") == {"ok": False, "error": "invalid key"}
    assert desk.audit[-1]["outcome"] == "invalid_key" and desk.audit[-1]["key"] is None


def test_the_result_size_cap_and_the_rate_cap_stop_a_key_independently() -> None:
    async def go():
        async with open_world("hardened") as w:
            small = w.desk.issue_key("sam", collections={"archive"}, ceiling="T1", limits=Limits(max_result_bytes=700))
            sizes = [await (await w.client(small)).call("read", doc_id=f"ARCH-{i:03d}") for i in range(1, 8)]
            fast = w.desk.issue_key("sam", collections={"archive"}, ceiling="T1", limits=Limits(max_per_minute=3))
            client = await w.client(fast)
            burst = [await client.call("read", doc_id="ARCH-001") for _ in range(5)]
            w.clock.advance(61)
            after_a_minute = await client.call("read", doc_id="ARCH-001")
            return sizes, burst, after_a_minute

    sizes, burst, after = run(go())
    assert sizes[0]["ok"] and sizes[-1]["error"] == "result size limit reached"
    assert [r.get("ok", False) for r in burst] == [True, True, True, False, False] and burst[-1]["error"] == "rate limit reached"
    assert after["ok"]


def test_a_key_granted_approve_own_can_apply_a_low_risk_change_and_is_recorded_as_the_approver() -> None:
    async def go():
        async with open_world("hardened") as w:
            client = await w.client("selfapprover")
            proposal = await client.call("propose_change", doc_id="RB-3", new_body="Ask the broker for the list.", reason="r")
            done = await client.call("approve", proposal_id=proposal["proposal"])
            return w, done

    w, done = run(go())
    assert done["ok"] and w.desk.docs["RB-3"].applied_by == f"key:{w.desk.keys[w.keys['selfapprover']].id}"


def test_read_only_collections_and_missing_grants_refuse_a_proposal() -> None:
    async def go():
        async with open_world("hardened") as w:
            reader, nothing = await w.client("reader"), await w.client("nothing")
            return (
                await reader.call("propose_change", doc_id="ARCH-001", new_body="x", reason="r"),
                await nothing.call("propose_change", doc_id="RB-1", new_body="x", reason="r"),
                await (await w.client("admin")).call("propose_change", doc_id="RB-1", new_body="x", reason="r"),
            )

    read_only, no_access, no_grant = run(go())
    assert read_only["error"] == "this collection is read-only for assistants"
    assert no_access["error"] == "this key may not propose changes"
    assert no_grant["error"] == "this key may not propose changes"


def test_the_audit_log_keeps_ids_and_sizes_not_document_text() -> None:
    async def go():
        async with open_world("hardened") as w:
            client = await w.client("reader")
            await client.call("read", doc_id="RB-1")
            await client.call("propose_change", doc_id="RB-1", new_body="secret new text", reason="r")
            return w

    w = run(go())
    rows = json.dumps(w.desk.audit)
    assert "secret new text" not in rows and "Check the port notice" not in rows
    assert {r["tool"] for r in w.desk.audit} == {"read", "propose_change"} and all(r["result_bytes"] > 0 for r in w.desk.audit)


def test_every_tool_is_listed_identically_by_the_weak_and_the_hardened_desk() -> None:
    async def tools(target):
        async with open_world(target) as w:
            gateway = await w.gateway("reader")
            return sorted((v.server, v.name, v.description) for v in await gateway.tools())

    assert run(tools("weak")) == run(tools("hardened"))


def test_the_approval_queue_is_shorter_when_low_risk_changes_may_be_applied_by_an_agent() -> None:
    result = measure()
    every, by_class = result["A: every change waits for a person"], result["B: approval by risk class"]
    assert every["waiting_for_a_person"] == 100 and by_class["waiting_for_a_person"] == 20 and by_class["applied_by_agent"] == 80
