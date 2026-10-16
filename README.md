Project: Multi-Tenant AI Customer Support Resolution Platform

An agent platform that resolves support tickets end to end. It answers from a company’s knowledge base, looks up orders and accounts, and takes actions like refunds or ticket updates. Risky actions need human approval, and unresolved cases escalate to a human with a full summary. Companies pay for exactly this, so it reads as real work rather than a demo.

How it works
A ticket arrives (email, chat widget, or webhook).
A router classifies intent and urgency (billing, technical, refund, general).
A LangGraph workflow runs the right path:
Knowledge agent: RAG over docs, FAQs, and past resolved tickets
Action agent: calls tools (order lookup, CRM, refund API) through MCP servers
Policy/guardrail node: checks the draft against company rules and scans for PII or injection
Human approval node: pauses with an interrupt for refunds above a threshold
Escalation node: hands off to a human with a summary and the steps already tried
The reply goes out, and the outcome is logged for evals.
Where each skill shows up
Skill	Where you use it
LLM fundamentals	Model routing (small model for classification, larger for reasoning), structured outputs, token and cost budgets
Prompt engineering	Versioned prompts per tenant, few-shot examples, JSON schema outputs
Embeddings and vector DB	pgvector or Qdrant with per-tenant isolation
RAG	Chunking, hybrid search, reranking, query rewriting, citations in every answer
LangChain	Retrievers, loaders, tool definitions, model abstraction
LangGraph	State, conditional edges, checkpointer in Postgres, interrupts, subgraphs, retries
Agentic concepts	Multi-agent supervisor, ReAct tool use, reflection step before sending
MCP	Internal tools (orders, CRM) exposed as MCP servers
Context engineering	Conversation summarization, loading only relevant tickets and docs per step
Guardrails and security	Prompt injection defense, tool permission scoping, PII redaction, audit log
Memory	Per-customer history across tickets
Evaluation	Golden dataset of tickets, LLM-as-judge, RAG faithfulness metrics, regression tests in CI
Observability	LangSmith tracing, cost per ticket, latency dashboards
Production	FastAPI, Redis queue, Celery/workers, Docker, CI/CD, cloud deploy
Features that make it production grade
Multi-tenancy: each company has its own knowledge base, prompts, and policies, with data isolation
Auth and RBAC: admin, agent, and viewer roles
Durable execution: a crashed workflow resumes from its checkpoint
Eval gate in CI: a prompt or model change that drops resolution accuracy fails the build
Cost controls: per-tenant token budgets, caching, and fallback to cheaper models
Rate limiting and retries around every external call
Admin dashboard: resolution rate, escalation rate, average cost per ticket, human override rate
Audit trail: every tool call and approval recorded
Feedback loop: human corrections feed back into the eval set
Suggested stack
Backend: Python, FastAPI, Pydantic
Orchestration: LangGraph, LangChain, MCP
Data: Postgres with pgvector, Redis
Frontend: Next.js or React for the dashboard and approval inbox
Infra: Docker, GitHub Actions, AWS or GCP
Observability: LangSmith, plus Prometheus and Grafana if you want extra depth
Build order
Basic RAG over a knowledge base, with an eval set from day one
Add tool calling and a single LangGraph agent
Add router, guardrails, and human-in-the-loop approval
Add multi-tenancy, auth, and the dashboard
Add the eval-gated CI pipeline, tracing, and deployment
Load test it and record real numbers
Resume bullets (fill in your real numbers)
Built a multi-tenant AI support platform using LangGraph and RAG that autonomously resolves X% of tickets, with human-in-the-loop approval for sensitive actions
Designed hybrid retrieval (vector + BM25 with reranking) that improved answer faithfulness from X to Y on a 200-ticket eval set
Implemented an eval-gated CI pipeline that blocks regressions in resolution accuracy before deployment
Reduced cost per ticket by X% through model routing, caching, and context compaction
Secured tool access with scoped MCP servers, prompt-injection defenses, and a full audit trail
Tips to make it credible
Measure everything. Numbers from your own eval set beat any list of buzzwords.
Deploy it live with a demo link and a short architecture write-up or video.
Use realistic data: public support datasets or a public product’s docs, so the evals mean something.
Be ready to explain tradeoffs: why a workflow here instead of a free agent, why this chunking strategy, what failed and how you fixed it. Interviewers care more about that than the stack.
