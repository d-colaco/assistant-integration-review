"""The layer that composes servers for an assistant: it lists their tools and forwards calls.

``NaiveGateway`` passes everything through. ``PolicyGateway`` adds the two controls that belong to the party
connecting several servers, because no single server can enforce them:

* **description pinning.** The tool set is reviewed once (``review``) and the hash of each tool's description
  and schema is kept. A tool whose description later changes, or that was never reviewed, is withheld from the
  assistant and cannot be called, and the event is logged.
* **tier flow.** The gateway tracks the highest tier the session has read. A write on a server of a lower tier
  is refused: confidential text read from one server must not end up on a public one.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

from dclabagent.seed import rank


@dataclass
class Entry:
    name: str
    session: ClientSession
    tier: str
    write_tools: frozenset[str]


@dataclass
class ToolView:
    server: str
    name: str
    description: str
    schema: dict = field(default_factory=dict)


def text_of(result) -> str:
    return "".join(part.text for part in result.content if getattr(part, "text", None))


def _digest(tool) -> str:
    return hashlib.sha256(json.dumps([tool.description, tool.inputSchema], sort_keys=True).encode()).hexdigest()


class NaiveGateway:
    def __init__(self, stack: AsyncExitStack) -> None:
        self._stack = stack
        self.servers: dict[str, Entry] = {}
        self.events: list[dict[str, Any]] = []

    async def add(self, name: str, server, tier: str, write_tools=()) -> None:
        session = await self._stack.enter_async_context(create_connected_server_and_client_session(server._mcp_server))
        self.servers[name] = Entry(name, session, tier, frozenset(write_tools))

    async def review(self) -> None:
        """The naive gateway has nothing to review."""

    async def tools(self) -> list[ToolView]:
        views = []
        for entry in self.servers.values():
            for tool in (await entry.session.list_tools()).tools:
                views.append(ToolView(entry.name, tool.name, tool.description or "", tool.inputSchema))
        return views

    async def call(self, server: str, tool: str, arguments: dict[str, Any]) -> str:
        result = await self.servers[server].session.call_tool(tool, arguments)
        return text_of(result)


class PolicyGateway(NaiveGateway):
    def __init__(self, stack: AsyncExitStack) -> None:
        super().__init__(stack)
        self.pins: dict[tuple[str, str], str] = {}
        self.taint = "T0"

    def _log(self, kind: str, **details: Any) -> None:
        event = {"event": kind, **details}
        if event not in self.events:  # a withheld tool is noticed on every listing and call; log it once
            self.events.append(event)

    async def review(self) -> None:
        for entry in self.servers.values():
            for tool in (await entry.session.list_tools()).tools:
                self.pins[(entry.name, tool.name)] = _digest(tool)

    async def _trusted(self, entry: Entry) -> dict[str, Any]:
        trusted = {}
        for tool in (await entry.session.list_tools()).tools:
            pinned = self.pins.get((entry.name, tool.name))
            if pinned == _digest(tool):
                trusted[tool.name] = tool
            else:
                self._log("description-changed" if pinned else "unreviewed-tool", server=entry.name, tool=tool.name)
        return trusted

    async def tools(self) -> list[ToolView]:
        views = []
        for entry in self.servers.values():
            for name, tool in (await self._trusted(entry)).items():
                views.append(ToolView(entry.name, name, tool.description or "", tool.inputSchema))
        return views

    async def call(self, server: str, tool: str, arguments: dict[str, Any]) -> str:
        entry = self.servers[server]
        if tool not in await self._trusted(entry):
            return json.dumps({"ok": False, "error": "tool withheld: its description changed since it was reviewed"})
        if tool in entry.write_tools and rank(entry.tier) < rank(self.taint):
            self._log("tier-flow-refused", server=server, tool=tool, taint=self.taint, server_tier=entry.tier)
            return json.dumps({"ok": False, "error": f"refused: this session has read {self.taint} data and {server} is {entry.tier}"})
        text = await super().call(server, tool, arguments)
        if tool not in entry.write_tools:
            try:
                tier = json.loads(text).get("tier") or entry.tier
            except (ValueError, AttributeError):
                tier = entry.tier
            # a result that names its tier counts as that tier; one that does not counts as its server's tier
            if tier in ("T0", "T1", "T2") and rank(tier) > rank(self.taint):
                self.taint = tier
        return text
