# Multi-Tenant AI Customer Support Resolution Platform

An agent platform that resolves support tickets end to end. It answers from a company's knowledge base, looks up orders and accounts, and takes actions such as refunds or ticket updates. Risky actions require human approval, and unresolved cases escalate to a person with a full summary of what was already tried.

> **Status: early scaffold.** The repository currently contains the project foundation — local environment, configuration, and quality tooling. No resolution logic is implemented yet. See [Project status](#project-status).

---

## How it works

```
ticket (email | chat | webhook)
        │
        ▼
   router — classifies intent + urgency
        │
        ▼
   LangGraph workflow
        ├── knowledge agent ..... RAG over docs, FAQs, past resolved tickets
        ├── action agent ........ order lookup, CRM, refunds via MCP servers
        ├── policy node ......... validates the proposed action; PII + injection checks
        ├── approval node ....... interrupt + wait for a human above a threshold
        └── escalation node ..... hand off with a summary and the steps tried
        │
        ▼
   reply sent · outcome logged for evaluation
```

The central safety property: **the model proposes a structured action, and a deterministic policy layer authorises it.** No path exists from model output directly to a privileged call.

## Stack

| Layer | Choice |
|---|---|
| Backend | Python, FastAPI, Pydantic |
| Orchestration | LangGraph, LangChain, MCP |
| Data | PostgreSQL + pgvector, Redis |
| Frontend | Next.js (admin dashboard and approval inbox) |
| Infra | Docker, GitHub Actions |
| Observability | LangSmith, cost and latency dashboards |

---

## Getting started

**Prerequisites:** Docker Desktop (running), Python 3.12+, git.

### 1. Clone and configure

```bash
git clone https://github.com/Hxrshxl/Multi-Tenant-AI-Customer-Support-Resolution-Platform.git
cd Multi-Tenant-AI-Customer-Support-Resolution-Platform
```

Copy the environment template. Every variable without a default is required — the app fails at startup and names any that are missing.

```bash
cp .env.example .env          # Windows: copy .env.example .env
```

### 2. Start the stack

```bash
docker compose up -d
```

This brings up PostgreSQL with the `vector` extension enabled, Redis, and the API on <http://localhost:8000>.

### 3. Set up the development environment

```bash
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pre-commit install
```

### 4. Verify

```bash
python -m app.cli check       # confirms Postgres, pgvector and Redis are reachable
python scripts/check.py       # lint, format, type check, tests — one command
```

Both should pass. If `app.cli check` fails, the stack is probably not up yet.

### Running the API on your host

Useful for development with auto-reload, instead of the container:

```bash
uvicorn app.main:create_app --factory --reload
```

The app is exposed as a factory rather than a module-level object, so importing it has no side effects and configuration is read at startup rather than at import.

---

## HTTP surface

| Endpoint | Purpose |
|---|---|
| `GET /` | Service identity and version |
| `GET /health` | Liveness — process is up. Checks no dependencies, so an outage never causes a restart loop |
| `GET /ready` | Readiness — `200` when Postgres and Redis are reachable, `503` otherwise |
| `GET /docs` | OpenAPI UI (disabled when `APP_ENV=production`) |

Every request carries a correlation ID. Send `X-Request-ID` to join an existing
trace, or one is generated; either way it comes back on the response and appears
on every log line that request produced.

Every failure returns the same envelope, so clients branch on `code` and humans
quote `requestId`:

```json
{"error": {"code": "not_found", "message": "No ticket with that id.", "requestId": "a1b2c3…"}}
```

## Commands

| Command | What it does |
|---|---|
| `python scripts/check.py` | Lint, format check, type check and tests |
| `python scripts/check.py --fix` | Auto-fix lint and formatting first |
| `python -m app.cli check` | Verify Postgres, pgvector and Redis connectivity |
| `python -m app.cli seed` | Load sample tenants and tickets *(no-op until the schema lands)* |
| `docker compose up -d` | Start the local stack |
| `docker compose down -v` | Stop and remove volumes (wipes local data) |

---

## Layout

```
app/
  config.py        validated settings; fails fast and names missing variables
  main.py          FastAPI factory
  cli.py           developer commands
docker/
  postgres/        first-run SQL (enables pgvector)
scripts/
  check.py         the single quality-check entry point
tests/
Team/              senior engineering agent personas and working agreements
```

---

## Project status

Work is tracked as a Jira backlog of 12 epics. Build order is dependency-driven rather than layer-driven: the backend and evaluation harness come first, and the frontend starts at epic 10.

| Phase | Epics | Focus |
|---|---|---|
| 1 | Foundation, retrieval (RAG), evaluation harness | Backend / ML |
| 2 | Ticket intake and routing, LangGraph orchestration | Backend |
| 3 | Tools via MCP, guardrails and policy, human approval | Backend |
| 4 | Multi-tenancy and auth, dashboard, observability and cost | Backend + Frontend |
| 5 | Eval-gated CI, deployment, load testing | DevOps |

**Done:** repository scaffold, one-command local environment, configuration with fail-fast validation, quality tooling.

**Next:** FastAPI service skeleton with correlation-ID logging and a standard error envelope, then the core data model.

A deliberate early decision: `tenant_id` is carried through the schema and request context from the first commit, so multi-tenancy in phase 4 is an enforcement change rather than a retrofit through every query.

The full specification, open decisions and recorded risks live in [`project idea.md`](./project%20idea.md).

---

## Engineering standards

This project is built to a defined bar rather than to "it works". Every change is expected to carry its tests and observability, and the measurable claims come from a real evaluation set rather than impression.

The working agreements — ownership boundaries, decision frameworks and definitions of done for each discipline — are in [`Team/`](./Team/README.md).
