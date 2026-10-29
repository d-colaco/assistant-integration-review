"""The hardened desk: the same tool surface, with the rules enforced by the system, not by the model.

* a key belongs to a user and can only narrow that user's collections and tier, never widen them
* above the key's tier ceiling, or outside its collections, the answer is the same "not found" as for a
  missing document, so the answer does not confirm that the document exists
* a write is a proposal with a diff and an expiry; applying it is a separate act with a recorded approver
* a key cannot approve its own proposal unless it was granted ``approve_own``; the risk class of the
  collection decides whether an agent approver may apply a change or only a person may
* ``send_report`` never sends: the desk exposes data, it does not push it out
* per-key caps on calls, result bytes and calls per minute; every call is audited; a key can be revoked
  while a session is open
"""

from __future__ import annotations

import difflib
import itertools
import json
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from dclabagent.seed import COLLECTIONS, USERS, Doc, rank, seed_docs, top_tier

NOT_FOUND = {"ok": False, "error": "document not found"}
PROPOSAL_TTL = 3600.0
RATE_WINDOW = 60.0


class KeyScopeError(ValueError):
    """Raised when a key would be wider than the user it belongs to."""


@dataclass(frozen=True)
class Limits:
    max_calls: int | None = None
    max_result_bytes: int | None = None
    max_per_minute: int | None = None


@dataclass
class Key:
    id: str
    secret: str
    user: str
    collections: frozenset[str]
    ceiling: str
    grants: frozenset[str]
    limits: Limits
    revoked_at: float | None = None
    calls: int = 0
    bytes_used: int = 0
    recent: deque = field(default_factory=deque)


@dataclass
class Proposal:
    id: str
    doc_id: str
    new_body: str
    diff: str
    reason: str
    key_id: str
    risk: str
    created_at: float
    expires_at: float
    status: str = "pending"  # pending, applied, expired
    approved_by: str | None = None


class HardenedDesk:
    name = "hardened"

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self.docs: dict[str, Doc] = seed_docs()
        self.outbox: list[dict[str, str]] = []  # stays empty: nothing is ever sent
        self.proposals: dict[str, Proposal] = {}
        self.audit: list[dict[str, Any]] = []
        self.keys: dict[str, Key] = {}
        self._ids = itertools.count(1)

    # --- operator side -------------------------------------------------------------------------------

    def issue_key(
        self,
        user: str,
        *,
        collections: frozenset[str] | set[str] | None = None,
        ceiling: str | None = None,
        grants: frozenset[str] | set[str] | tuple = (),
        limits: Limits | None = None,
    ) -> str:
        if user not in USERS:
            raise KeyScopeError(f"unknown user {user}")
        user_collections, user_ceiling = USERS[user]
        wanted = frozenset(user_collections if collections is None else collections)
        wanted_ceiling = user_ceiling if ceiling is None else ceiling
        if not wanted <= user_collections or rank(wanted_ceiling) > rank(user_ceiling):
            raise KeyScopeError("a key can narrow its user's access, never widen it")
        key_id = f"K{next(self._ids)}"
        secret = f"hk_{key_id}_{next(self._ids)}"
        self.keys[secret] = Key(key_id, secret, user, wanted, wanted_ceiling, frozenset(grants), limits or Limits())
        return secret

    def revoke_key(self, secret: str) -> None:
        key = self.keys.get(secret)
        if key is not None and key.revoked_at is None:
            key.revoked_at = self.clock()

    def person_approve(self, proposal_id: str, person: str) -> dict[str, Any]:
        """A person applies any pending proposal, whatever its risk class. This is not an MCP tool."""
        proposal = self.proposals.get(proposal_id)
        if proposal is None or proposal.status != "pending":
            return {"ok": False, "error": "no pending proposal"}
        if self.clock() > proposal.expires_at:
            proposal.status = "expired"
            return {"ok": False, "error": "proposal expired"}
        return self._apply(proposal, f"person:{person}")

    # --- helpers -------------------------------------------------------------------------------------

    def _record(self, key: Key | None, session: str, tool: str, args: dict[str, Any], outcome: str, result: dict[str, Any], docs=()) -> None:
        size = len(json.dumps(result))
        if key is not None:
            key.bytes_used += size
        self.audit.append(
            {
                "ts": self.clock(),
                "session": session,
                "key": key.id if key else None,
                "user": key.user if key else None,
                "tool": tool,
                "args": args,
                "outcome": outcome,
                "result_bytes": size,
                "docs": list(docs),
            }
        )

    def _enter(self, secret: str, session: str, tool: str, args: dict[str, Any]) -> tuple[Key | None, dict[str, Any] | None]:
        """Resolve and meter the key. Returns (key, None) to proceed or (None, refusal), already audited."""
        key = self.keys.get(secret)
        if key is None:
            refusal = {"ok": False, "error": "invalid key"}
            self._record(None, session, tool, args, "invalid_key", refusal)
            return None, refusal
        now = self.clock()
        if key.revoked_at is not None:
            refusal = {"ok": False, "error": "key revoked"}
            self._record(key, session, tool, args, "revoked", refusal)
            return None, refusal
        limits = key.limits
        while key.recent and now - key.recent[0] > RATE_WINDOW:
            key.recent.popleft()
        reason = None
        if limits.max_calls is not None and key.calls >= limits.max_calls:
            reason = "call limit reached"
        elif limits.max_result_bytes is not None and key.bytes_used >= limits.max_result_bytes:
            reason = "result size limit reached"
        elif limits.max_per_minute is not None and len(key.recent) >= limits.max_per_minute:
            reason = "rate limit reached"
        if reason:
            refusal = {"ok": False, "error": reason}
            self._record(key, session, tool, args, "limit", refusal)
            return None, refusal
        key.calls += 1
        key.recent.append(now)
        return key, None

    def _visible(self, key: Key, doc: Doc | None) -> bool:
        return doc is not None and doc.collection in key.collections and rank(doc.tier) <= rank(key.ceiling)

    def _apply(self, proposal: Proposal, approver: str) -> dict[str, Any]:
        doc = self.docs[proposal.doc_id]
        doc.body, doc.version, doc.applied_by = proposal.new_body, doc.version + 1, approver
        proposal.status, proposal.approved_by = "applied", approver
        return {"ok": True, "status": "applied", "proposal": proposal.id, "approved_by": approver}

    # --- tool surface --------------------------------------------------------------------------------

    def search(self, secret: str, session: str, query: str) -> dict[str, Any]:
        key, refusal = self._enter(secret, session, "search", {"query": query})
        if refusal:
            return refusal
        needle = query.lower()
        hits = [
            {"id": d.id, "title": d.title, "collection": d.collection}
            for d in self.docs.values()
            if self._visible(key, d) and (needle in d.title.lower() or needle in d.body.lower() or needle in d.id.lower())
        ]
        result = {"ok": True, "tier": top_tier(self.docs, hits), "results": hits}
        self._record(key, session, "search", {"query": query}, "ok", result)
        return result

    def read(self, secret: str, session: str, doc_id: str) -> dict[str, Any]:
        args = {"doc_id": doc_id}
        key, refusal = self._enter(secret, session, "read", args)
        if refusal:
            return refusal
        doc = self.docs.get(doc_id)
        if not self._visible(key, doc):
            # the same answer for a missing and for a forbidden document; only the operator's audit tells them apart
            self._record(key, session, "read", args, "missing" if doc is None else "denied", NOT_FOUND)
            return dict(NOT_FOUND)
        result = {"ok": True, "id": doc.id, "tier": doc.tier, "title": doc.title, "body": doc.body, "version": doc.version}
        self._record(key, session, "read", args, "ok", result, docs=[doc.id])
        return result

    def propose_change(self, secret: str, session: str, doc_id: str, new_body: str, reason: str) -> dict[str, Any]:
        args = {"doc_id": doc_id, "chars": len(new_body)}
        key, refusal = self._enter(secret, session, "propose_change", args)
        if refusal:
            return refusal
        doc = self.docs.get(doc_id)
        if "propose" not in key.grants:
            result = {"ok": False, "error": "this key may not propose changes"}
            self._record(key, session, "propose_change", args, "refused", result)
            return result
        if not self._visible(key, doc):
            self._record(key, session, "propose_change", args, "missing" if doc is None else "denied", NOT_FOUND)
            return dict(NOT_FOUND)
        risk = COLLECTIONS[doc.collection][1]
        if risk is None:
            result = {"ok": False, "error": "this collection is read-only for assistants"}
            self._record(key, session, "propose_change", args, "refused", result)
            return result
        diff = "\n".join(
            difflib.unified_diff(doc.body.splitlines(), new_body.splitlines(), f"{doc.id} v{doc.version}", "proposed", lineterm="")
        )
        proposal = Proposal(
            f"P-{next(self._ids)}", doc.id, new_body, diff, reason, key.id, risk, self.clock(), self.clock() + PROPOSAL_TTL
        )
        self.proposals[proposal.id] = proposal
        result = {"ok": True, "proposal": proposal.id, "status": "pending", "risk": risk, "diff": diff}
        self._record(key, session, "propose_change", args, "queued", result, docs=[doc.id])
        return result

    def approve(self, secret: str, session: str, proposal_id: str) -> dict[str, Any]:
        args = {"proposal_id": proposal_id}
        key, refusal = self._enter(secret, session, "approve", args)
        if refusal:
            return refusal
        proposal = self.proposals.get(proposal_id)
        doc = self.docs.get(proposal.doc_id) if proposal else None
        if "approve" not in key.grants and "approve_own" not in key.grants:
            result = {"ok": False, "error": "this key may not approve changes"}
            self._record(key, session, "approve", args, "refused", result)
            return result
        if proposal is None or not self._visible(key, doc):
            result = {"ok": False, "error": "proposal not found"}
            self._record(key, session, "approve", args, "missing", result)
            return result
        if proposal.status != "pending":
            result = {"ok": False, "error": f"proposal is {proposal.status}"}
            self._record(key, session, "approve", args, "refused", result)
            return result
        if self.clock() > proposal.expires_at:
            proposal.status = "expired"
            result = {"ok": False, "error": "proposal expired"}
            self._record(key, session, "approve", args, "refused", result)
            return result
        if proposal.key_id == key.id and "approve_own" not in key.grants:
            result = {"ok": False, "error": "a key cannot approve its own proposal"}
            self._record(key, session, "approve", args, "refused", result)
            return result
        if proposal.risk == "high":
            result = {"ok": False, "error": "held: this path needs a person to approve", "status": "pending"}
            self._record(key, session, "approve", args, "held", result)
            return result
        result = self._apply(proposal, f"key:{key.id}")
        self._record(key, session, "approve", args, "ok", result, docs=[proposal.doc_id])
        return result

    def send_report(self, secret: str, session: str, to: str, text: str) -> dict[str, Any]:
        args = {"to": to, "chars": len(text)}
        key, refusal = self._enter(secret, session, "send_report", args)
        if refusal:
            return refusal
        result = {"ok": False, "error": "this desk never sends: it exposes data, it does not push it out"}
        self._record(key, session, "send_report", args, "refused", result)
        return result

    def session_report(self, secret: str, session: str) -> dict[str, Any]:
        """What this session did, from the audit log: the operator's answer to 'what did the assistant see?'."""
        key = self.keys.get(secret)
        if key is None:
            return {"ok": False, "error": "invalid key"}
        rows = [r for r in self.audit if r["session"] == session]
        outcomes: dict[str, int] = defaultdict(int)
        tools: dict[str, int] = defaultdict(int)
        seen: list[str] = []
        for row in rows:
            outcomes[row["outcome"]] += 1
            tools[row["tool"]] += 1
            seen += [d for d in row["docs"] if d not in seen and row["tool"] == "read"]
        revoked = next((r["ts"] for r in rows if r["outcome"] == "revoked"), None)
        return {
            "ok": True,
            "session": session,
            "key": key.id,
            "user": key.user,
            "calls": len(rows),
            "by_tool": dict(tools),
            "by_outcome": dict(outcomes),
            "documents_read": seen,
            "result_bytes": sum(r["result_bytes"] for r in rows),
            "first_call": rows[0]["ts"] if rows else None,
            "last_call": rows[-1]["ts"] if rows else None,
            "revoked_at": key.revoked_at,
            "first_call_after_revocation": revoked,
        }

    def whoami(self, secret: str, session: str) -> dict[str, Any]:
        key, refusal = self._enter(secret, session, "whoami", {})
        if refusal:
            return refusal
        result = {
            "ok": True, "key": key.id, "user": key.user, "collections": sorted(key.collections), "ceiling": key.ceiling,
            "grants": sorted(key.grants),
        }
        self._record(key, session, "whoami", {}, "ok", result)
        return result
