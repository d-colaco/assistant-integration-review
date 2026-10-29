PY := .venv/bin/python

.PHONY: install test lint rubric queue diagrams screenshots llm-run evidence serve-weak serve-hardened

install:                ## virtualenv with the lab, its test tools and Playwright for the evidence frames
	@test -x $(PY) || python3 -m venv .venv
	$(PY) -m pip install -e ".[dev,evidence]"

test:                   ## the attack suite, the rubric evidence and the unit tests
	$(PY) -m pytest -q

lint:
	.venv/bin/ruff check .

rubric:                 ## run every control against both servers and write reports/rubric.md
	$(PY) -m dclabagent rubric

queue:                  ## the approval queue under two policies (a synthetic workload)
	$(PY) -m dclabagent queue

diagrams:               ## render demo/diagrams/*.mmd to SVG (light and dark) and PNG (needs Node and Chromium)
	$(PY) scripts/render_diagrams.py

screenshots:            ## rebuild the evidence frames in demo/screenshots from live runs (needs Playwright's Chromium)
	PYTHONPATH=src $(PY) scripts/screenshots.py

llm-run:                ## optional: a local model reads the prose planted tickets (OLLAMA_URL, default 127.0.0.1:11434)
	$(PY) -m dclabagent llm-run --runs 3 --out demo/runs/llm-run.json

evidence: diagrams screenshots

serve-weak:             ## the weak desk over stdio for a real MCP client (DESK_KEY=reader|approver|admin|...)
	$(PY) -m dclabagent serve weak

serve-hardened:         ## the hardened desk over stdio for a real MCP client
	$(PY) -m dclabagent serve hardened
