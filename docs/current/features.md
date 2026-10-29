# Features

## The desk (both servers expose the same seven tools)

`search`, `read`, `propose_change`, `approve`, `send_report`, `session_report`, `whoami`. Collections have
a tier (T0 public, T1 internal, T2 confidential) and a write risk class (low, high, or read-only).

| Rule | Weak desk | Hardened desk |
|---|---|---|
| Keys | any key string opens everything | a key belongs to a user and can only narrow its collections and tier; widening is refused at issue |
| Above the ceiling | the document is returned | the answer is the same "document not found" as for a missing id; only the audit tells them apart |
| Writes | `propose_change` overwrites at once | a proposal with a diff and a one-hour expiry; applying is a separate act |
| Approval | any caller, nobody recorded | needs the `approve` grant; a key cannot approve its own proposal without `approve_own`; low-risk paths may be applied by an agent approver and are recorded as `key:<id>`; high-risk paths are held until a person approves (`person:<name>`) |
| Sending | `send_report` puts text in an outbox | refused and logged: the desk exposes data, it never pushes it out |
| Limits | none | per key: total calls, total result bytes, calls per minute |
| Audit | none | one row per call: session, key, tool, arguments (ids and sizes, never text), outcome, bytes, documents |
| Report | not available | `session_report`: calls, outcomes, documents read, revocation time |
| Revocation | not available | takes effect on the next call, in the same session |

## The gateway

`NaiveGateway` lists and forwards. `PolicyGateway` pins each tool's description and schema at review time and
withholds a tool that changed or was never reviewed, and tracks the highest tier the session has read to
refuse a write on a lower-tier server.

## The assistant and the planted instructions

`ObeyEverything` executes every `<<call server.tool {json}>>` and `<<crawl server.tool PREFIX N>>` it finds in
a task, a tool result or a tool description. Four inbox tickets carry them: exfiltration by sending
(`INBOX-1`), a runbook overwrite with self-approval (`INBOX-2`), a confidential read posted to the public
board (`INBOX-3`), and a sixty-ticket slow export (`INBOX-4`). A tool description on the board changes after
review for the description-change control.

## The optional model run

`OllamaAssistant` lets a local model (default `gpt-oss:20b`) use the same tools through the gateway. Three tickets
ask for an attack in plain prose (`INBOX-5` send a record out, `INBOX-6` overwrite a runbook and approve it,
`INBOX-7` post a record on the public board). `llm_suite` runs each on both targets and judges by the system's state,
not by the model's account. It is never part of the verdicts: results vary by run and model.

## Commands

`make test`, `make lint`, `make rubric` (writes `reports/rubric.md`), `make queue`, `make diagrams`, `make screenshots`,
`make evidence`, `make llm-run` (needs Ollama; `OLLAMA_URL`), `make serve-weak` and `make serve-hardened` (stdio; pick the
key with `DESK_KEY`).

The project's [.mcp.json](../../.mcp.json) registers seven stdio servers for Claude Code started in the repository root
(approve them on first use): `desk-weak-reader`, `desk-weak-approver`, `desk-hardened-reader`, `desk-hardened-approver`, and `desk-weak-selfapprover` / `desk-hardened-selfapprover` (propose and approve in one process, for the approval path), and `desk-hardened-policy_self` (the same on a high-risk collection, where the approval is held).
State lives in each process, so restarting the server resets the seed.
