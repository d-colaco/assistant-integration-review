"""Serve a desk over stdio so a real MCP client can connect to it (a client such as Claude Code or MCP Inspector).

The key is picked by name from the lab's keys (``DESK_KEY=reader``, ``approver``, ``admin``, ...). State lives in the
process: restart it and the seed returns. The weak desk is for attacking on a laptop; never expose it.
"""

from __future__ import annotations

import sys

from dclabagent.hardened import HardenedDesk
from dclabagent.servers import build_desk_server
from dclabagent.weak import WeakDesk
from dclabagent.world import issue_lab_keys


def serve_stdio(target: str, key_name: str | None) -> None:
    desk = WeakDesk() if target == "weak" else HardenedDesk()
    keys = issue_lab_keys(desk)
    name = key_name or "reader"
    if name not in keys:
        sys.exit(f"DESK_KEY must be one of: {', '.join(keys)}")
    build_desk_server(desk, keys[name]).run("stdio")
