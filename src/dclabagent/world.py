"""One lab world: a desk (weak or hardened), the public board, a clock, a set of keys and the gateway in front.

``target`` picks the pairing under test: the weak desk behind a naive gateway, or the hardened desk behind a
policy gateway. Keys are issued the same way for both; the weak desk simply ignores what a key says.
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from mcp import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

from dclabagent.gateway import NaiveGateway, PolicyGateway, text_of
from dclabagent.hardened import HardenedDesk, Limits
from dclabagent.seed import COLLECTIONS
from dclabagent.servers import BOARD_TIER, DESK_TIER, Board, build_desk_server
from dclabagent.weak import WeakDesk

TARGETS = ("weak", "hardened")
START = 1_000_000.0


class FakeClock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class DeskClient:
    """A direct MCP client to the desk, bound to one key; a new one is a new session."""

    def __init__(self, session: ClientSession, session_id: str) -> None:
        self._session = session
        self.session_id = session_id

    async def call(self, tool: str, **arguments: Any) -> dict[str, Any]:
        return json.loads(text_of(await self._session.call_tool(tool, arguments)))


def issue_lab_keys(desk) -> dict[str, str]:
    every = set(COLLECTIONS)
    return {
        "reader": desk.issue_key(
            "sam", collections={"faq", "inbox", "runbooks", "archive"}, ceiling="T1", grants={"propose"},
            limits=Limits(max_calls=25, max_result_bytes=12_000, max_per_minute=20),
        ),
        "nothing": desk.issue_key("sam", collections=set(), ceiling="T1"),
        "approver": desk.issue_key("sam", collections={"runbooks", "policies"}, ceiling="T1", grants={"approve"}),
        "selfapprover": desk.issue_key("sam", collections={"runbooks"}, ceiling="T1", grants={"propose", "approve_own"}),
        "policy_self": desk.issue_key("sam", collections={"policies"}, ceiling="T1", grants={"propose", "approve_own"}),
        "policy_writer": desk.issue_key("sam", collections={"policies"}, ceiling="T1", grants={"propose"}),
        "tier_probe": desk.issue_key("sam", collections=every, ceiling="T1"),
        "admin": desk.issue_key("sam", collections=every, ceiling="T2"),
    }


class World:
    def __init__(self, target: str, stack: AsyncExitStack) -> None:
        self.target = target
        self.stack = stack
        self.clock = FakeClock()
        self.desk = WeakDesk(self.clock) if target == "weak" else HardenedDesk(self.clock)
        self.board = Board()
        self.keys = issue_lab_keys(self.desk)

    async def client(self, key: str) -> DeskClient:
        server = build_desk_server(self.desk, self.keys.get(key, key))
        session = await self.stack.enter_async_context(create_connected_server_and_client_session(server._mcp_server))
        return DeskClient(session, server.session_id)  # type: ignore[attr-defined]

    async def gateway(self, key: str):
        """A gateway to the desk (as ``key``) and the board, with the tool set reviewed once."""
        gateway = NaiveGateway(self.stack) if self.target == "weak" else PolicyGateway(self.stack)
        await gateway.add("desk", build_desk_server(self.desk, self.keys.get(key, key)), DESK_TIER)
        await gateway.add("board", self.board.build_server(), BOARD_TIER, write_tools={"post_note"})
        await gateway.review()
        return gateway


@asynccontextmanager
async def open_world(target: str):
    if target not in TARGETS:
        raise ValueError(f"target must be one of {TARGETS}")
    async with AsyncExitStack() as stack:
        yield World(target, stack)
