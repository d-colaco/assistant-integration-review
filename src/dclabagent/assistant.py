"""A scripted assistant that obeys every instruction it finds.

It is the worst case for prompt injection: it treats any text it reads (a document, a tool result, a tool
description) as orders. Because it is a script, the run is deterministic and needs no model. If the rules hold
against this assistant, they hold however a real model is fooled; that is the point of enforcing them in the
system.

An instruction is written ``<<call server.tool {json}>>``. ``{{last}}`` stands for the body of the previous
result and ``{{proposal}}`` for the last proposal id. ``<<crawl server.tool PREFIX N>>`` reads PREFIX-001 to
PREFIX-N one at a time. Real attackers write prose; the format here only makes the test exact.
"""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass
from typing import Any

CALL = re.compile(r"<<call\s+(\w+)\.(\w+)\s*(\{.*?\})?\s*>>", re.DOTALL)
CRAWL = re.compile(r"<<crawl\s+(\w+)\.(\w+)\s+([A-Za-z]+)\s+(\d+)\s*>>")


@dataclass
class Step:
    server: str
    tool: str
    arguments: dict[str, Any]
    result: str
    origin: str  # task, description or result


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def instructions_in(text: str) -> list[tuple[str, str, dict[str, Any] | None, int | None]]:
    """Every instruction in a text, also inside the JSON strings of a tool result."""
    texts = [text]
    try:
        decoded = json.loads(text)
        if isinstance(decoded, (dict, list)):
            texts = list(_strings(decoded))  # the JSON escapes quotes, so read the strings, not the raw text
    except ValueError:
        pass
    found: list[tuple[str, str, dict[str, Any] | None, int | None]] = []
    seen: set[str] = set()
    for chunk in texts:
        for match in CALL.finditer(chunk):
            if match.group(0) in seen:
                continue
            seen.add(match.group(0))
            found.append((match.group(1), match.group(2), match.group(3), None))
        for match in CRAWL.finditer(chunk):
            if match.group(0) in seen:
                continue
            seen.add(match.group(0))
            for index in range(1, int(match.group(4)) + 1):
                found.append((match.group(1), match.group(2), json.dumps({"doc_id": f"{match.group(3)}-{index:03d}"}), index))
    return found


class ObeyEverything:
    def __init__(self, gateway, *, max_steps: int = 120, between_calls=None) -> None:
        self.gateway = gateway
        self.max_steps = max_steps
        self.between_calls = between_calls  # called after each step, e.g. to advance a test clock
        self.transcript: list[Step] = []
        self._last_body = ""
        self._last_proposal = ""

    def _fill(self, value: Any) -> Any:
        if isinstance(value, str):
            return value.replace("{{last}}", self._last_body).replace("{{proposal}}", self._last_proposal)
        if isinstance(value, dict):
            return {key: self._fill(item) for key, item in value.items()}
        return value

    async def run(self, task: list[tuple[str, str, dict[str, Any]]], *, read_descriptions: bool = True) -> list[Step]:
        queue: deque[tuple[str, str, dict[str, Any], str]] = deque((s, t, a, "task") for s, t, a in task)
        if read_descriptions:
            for view in await self.gateway.tools():
                self._enqueue(queue, view.description, "description")
        while queue and len(self.transcript) < self.max_steps:
            server, tool, arguments, origin = queue.popleft()
            arguments = self._fill(arguments)
            result = await self.gateway.call(server, tool, arguments)
            self.transcript.append(Step(server, tool, arguments, result, origin))
            try:
                data = json.loads(result)
            except ValueError:
                data = {}
            if isinstance(data, dict):
                self._last_body = str(data.get("body", result))
                self._last_proposal = str(data.get("proposal", self._last_proposal))
            self._enqueue(queue, result, "result")
            if self.between_calls:
                self.between_calls()
        return self.transcript

    @staticmethod
    def _enqueue(queue: deque, text: str, origin: str) -> None:
        for server, tool, raw, _ in instructions_in(text):
            try:
                arguments = json.loads(raw) if raw else {}
            except ValueError:
                continue
            queue.append((server, tool, arguments, origin))
