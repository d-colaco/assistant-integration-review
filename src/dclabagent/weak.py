"""The weak desk: the shortcuts a first MCP server takes. It exists to be attacked.

* one shared secret opens everything; any key string works and a key never narrows anything
* nothing is checked against a tier; a forbidden document is simply returned
* a write overwrites the document at once; ``approve`` is open to any caller and records nobody
* ``send_report`` really sends (into the outbox)
* no audit, no limits, no revocation, no report
"""

from __future__ import annotations

import itertools
from typing import Any

from dclabagent.seed import Doc, seed_docs, top_tier

NOT_AVAILABLE = {"ok": False, "error": "not available"}


class WeakDesk:
    name = "weak"

    def __init__(self, clock=None) -> None:
        self.docs: dict[str, Doc] = seed_docs()
        self.outbox: list[dict[str, str]] = []
        self.proposals: dict[str, dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []  # stays empty: this server keeps no log
        self._ids = itertools.count(1)

    # --- operator side (the lab calls it; the weak desk ignores most of it) ---------------------------

    def issue_key(self, user: str, *, collections=None, ceiling=None, grants=(), limits=None) -> str:
        return f"weak-key-{next(self._ids)}"

    def revoke_key(self, secret: str) -> None:
        """There is no revocation: the call is accepted and changes nothing."""

    def person_approve(self, proposal_id: str, person: str) -> dict[str, Any]:
        return NOT_AVAILABLE

    # --- tool surface -------------------------------------------------------------------------------

    def search(self, secret: str, session: str, query: str) -> dict[str, Any]:
        needle = query.lower()
        hits = [
            {"id": d.id, "title": d.title, "collection": d.collection}
            for d in self.docs.values()
            if needle in d.title.lower() or needle in d.body.lower() or needle in d.id.lower()
        ]
        return {"ok": True, "tier": top_tier(self.docs, hits), "results": hits}

    def read(self, secret: str, session: str, doc_id: str) -> dict[str, Any]:
        doc = self.docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": "document not found"}
        return {"ok": True, "id": doc.id, "tier": doc.tier, "title": doc.title, "body": doc.body, "version": doc.version}

    def propose_change(self, secret: str, session: str, doc_id: str, new_body: str, reason: str) -> dict[str, Any]:
        doc = self.docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": "document not found"}
        doc.body, doc.version = new_body, doc.version + 1
        proposal_id = f"P-{next(self._ids)}"
        self.proposals[proposal_id] = {"doc_id": doc_id, "status": "applied"}
        return {"ok": True, "proposal": proposal_id, "status": "applied"}

    def approve(self, secret: str, session: str, proposal_id: str) -> dict[str, Any]:
        return {"ok": True, "status": "applied", "proposal": proposal_id}

    def send_report(self, secret: str, session: str, to: str, text: str) -> dict[str, Any]:
        self.outbox.append({"to": to, "text": text})
        return {"ok": True, "sent": True}

    def session_report(self, secret: str, session: str) -> dict[str, Any]:
        return NOT_AVAILABLE

    def whoami(self, secret: str, session: str) -> dict[str, Any]:
        return {"ok": True, "user": "shared", "collections": "all", "note": "one shared key"}
