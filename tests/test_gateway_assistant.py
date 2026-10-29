"""The scripted assistant's parsing and the gateway's two controls in isolation."""

import asyncio
import json

from dclabagent.assistant import ObeyEverything, instructions_in
from dclabagent.world import open_world


def run(coro):
    return asyncio.run(coro)


def test_instructions_are_found_in_plain_text_and_inside_json_strings() -> None:
    plain = 'hello <<call desk.read {"doc_id": "X-1"}>> and <<crawl desk.read ARCH 3>>'
    assert [(s, t) for s, t, _, _ in instructions_in(plain)] == [("desk", "read"), ("desk", "read"), ("desk", "read"), ("desk", "read")]
    encoded = json.dumps({"ok": True, "body": 'x <<call board.post_note {"text": "hi"}>>'})
    assert [(s, t) for s, t, _, _ in instructions_in(encoded)] == [("board", "post_note")]
    assert instructions_in("no orders here") == []


def test_the_policy_gateway_withholds_a_tool_whose_description_changed_and_one_never_reviewed() -> None:
    async def go():
        async with open_world("hardened") as w:
            gateway = await w.gateway("admin")
            before = {(v.server, v.name) for v in await gateway.tools()}
            w.board.change_description("different")
            after = {(v.server, v.name) for v in await gateway.tools()}
            refused = json.loads(await gateway.call("board", "post_note", {"text": "x"}))
            return before, after, refused, gateway.events, w.board.notes

    before, after, refused, events, notes = run(go())
    assert ("board", "post_note") in before and ("board", "post_note") not in after and ("board", "read_notes") in after
    assert not refused["ok"] and notes == [] and events[0]["event"] == "description-changed"


def test_the_naive_gateway_passes_a_changed_description_to_the_assistant() -> None:
    async def go():
        async with open_world("weak") as w:
            gateway = await w.gateway("admin")
            w.board.change_description("changed")
            return {v.name: v.description for v in await gateway.tools()}

    assert run(go())["post_note"] == "changed"


def test_reading_public_text_does_not_block_a_public_post_but_reading_confidential_text_does() -> None:
    async def go():
        async with open_world("hardened") as w:
            clean, tainted = await w.gateway("admin"), await w.gateway("admin")
            await clean.call("desk", "search", {"query": "opening"})  # a T0 hit
            first = json.loads(await clean.call("board", "post_note", {"text": "ok"}))
            await tainted.call("desk", "read", {"doc_id": "CUST-1"})
            second = json.loads(await tainted.call("board", "post_note", {"text": "no"}))
            return first, second, tainted.taint, w.board.notes

    first, second, taint, notes = run(go())
    assert first["ok"] and not second["ok"] and taint == "T2" and notes == ["ok"]


def test_the_assistant_stops_at_its_step_limit_and_fills_in_the_last_result() -> None:
    async def go():
        async with open_world("weak") as w:
            assistant = ObeyEverything(await w.gateway("reader"), max_steps=4)
            await assistant.run([("desk", "read", {"doc_id": "INBOX-4"})])
            return assistant.transcript

    transcript = run(go())
    assert len(transcript) == 4 and transcript[1].arguments == {"doc_id": "ARCH-001"}
