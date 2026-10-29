# Architecture

```text
 scripted assistant (obeys every instruction it reads)
        │  tools(), call()
        ▼
 gateway ── NaiveGateway | PolicyGateway ──────────────┐
        │ MCP (in-memory transport)                    │ MCP
        ▼                                              ▼
 desk server (7 tools)                          board server (post_note, read_notes)
        │ calls                                        a public, T0, third-party server
        ▼
 WeakDesk | HardenedDesk   ◄── operator side: issue_key, revoke_key, person_approve (not MCP tools)
```

| File | Owns |
|---|---|
| `src/dclabagent/seed.py` | The invented domain: collections, tiers, users, documents and the planted instructions |
| `src/dclabagent/weak.py` | The weak desk: one shared key, no tiers, writes overwrite, anyone approves, sending works, no audit |
| `src/dclabagent/hardened.py` | The hardened desk: scoped keys, "not found" above the ceiling, proposals with a diff and expiry, approval policy, no sending, caps, audit, revocation, session report |
| `src/dclabagent/servers.py` | The MCP surface: the same seven tools over either desk, and the board |
| `src/dclabagent/gateway.py` | `NaiveGateway` (passes everything) and `PolicyGateway` (description pinning, tier flow) |
| `src/dclabagent/assistant.py` | The scripted assistant and its instruction syntax |
| `src/dclabagent/world.py` | One lab world per target: desk, board, clock, keys, gateway |
| `src/dclabagent/checks.py` | The ten controls; each decides by the system's own state |
| `src/dclabagent/rubric.py` | Runs every control on both targets and renders `reports/rubric.md` |
| `src/dclabagent/queue_measure.py` | The approval queue under two policies |
| `src/dclabagent/serve.py` | stdio server so a real MCP client can connect |
| `src/dclabagent/llm_assistant.py`, `llm_suite.py` | The optional assistant driven by a local model (Ollama), three prose planted tickets, and the suite that runs them on both targets |
| `src/dclabagent/evidence.py` | Live data for the evidence frames |
| `scripts/render_diagrams.py`, `scripts/screenshots.py` | Render `demo/diagrams` with Mermaid CLI and the frames in `demo/screenshots` with headless Chromium |
| `demo/` | The evidence package: README in a fixed demo format, presentation note, diagrams, frames, the model run record |

## Decisions

- **In-process MCP.** Tests use the SDK's in-memory transport, so the protocol is real (tool listing,
  schemas, results) and no sockets are needed. A server is bound to one key and one session id when built;
  over a network the key would arrive in a header.
- **Tools always return JSON text** with `ok` and an error text, so a refusal is data the assistant can
  read and the tests can compare.
- **The gateway is where multi-server controls live.** Description pinning and tier flow cannot be enforced
  by any single server, so they belong to the party that connects several; the weak pairing uses a naive one.
- **A test clock.** Expiry, rate limits and slow extraction use an injected clock (`world.FakeClock`).
- **Operator actions are not tools.** Issuing and revoking keys and a person's approval are methods the lab
  calls directly; an assistant cannot reach them.
