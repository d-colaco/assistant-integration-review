# Letting an assistant in: what the lab shows

## The problem

An assistant that reads documents and calls tools can be steered by text planted in a ticket, a tool result or a tool
description. No prompt reliably prevents that. So the question for an owner is not "will the model resist?" but "what
can it do if it does not?".

## What the lab does

Two MCP servers over an invented support desk: one built the way a first server often is (one shared key, no
tiers, writes overwrite, anyone approves, sending works, no log), one hardened (scoped keys, "not found" above the tier,
writes as proposals with a diff and an expiry, approval by risk class, no sending, caps, an audit log, revocation).
One suite of ten attacks runs against both. The assistant in the suite is a script that obeys every instruction it
reads, so the run is deterministic and needs no model: if the rules hold against that, they hold however a real model
is fooled.

## What it shows

- The planted-instruction run: on the weak desk a confidential record is sent out and a runbook is overwritten; on the
  hardened desk the read is "not found", sending is refused, the change is a pending proposal, and the self-approval is
  refused. Every step is in the audit log.
- Three controls that no single server can enforce are done at the point where servers are combined: a changed tool
  description is withheld, and confidential data read from one server cannot be written to a public one.
- The approval queue: with approval by risk class, 20 of 100 changes wait for a person instead of 100.
- The rubric: ten controls, pass or fail, each with the test that is its evidence. There is no total score.

## The real-model run

A local model (gpt-oss:20b through Ollama) read three tickets that asked, in plain prose, for an attack. It followed
the ticket that asked it to send a confidential record out in 2 of 17 runs on the weak desk, and then did exactly that.
It never tried it on the hardened desk (0 of 17) and did not try the other two attacks in 3 runs each. About one run in
eight is rare for a single conversation and routine for a system that runs thousands of them. The hardened desk was
never reached by a fooled model live, so frame 09 replays the model's recorded calls on it. A larger or different model would behave differently, which is the reason
no rule here depends on the model resisting.

## Limits to state

- The weak server is weak on purpose and the hardened one was written to pass: the lab shows the controls can be
  implemented and tested, not that any product has them.
- A script is not a model: the scripted assistant obeys the lab's own instruction syntax.
- Quotation marks, delimiters and "ignore previous instructions" prompts are not controls and are not tested.
- The lab rates only its own two servers.
- There is no public endpoint.
