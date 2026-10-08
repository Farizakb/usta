# ADR-015: No agent framework (LangChain / LangGraph)
Status: accepted
Date: 2026-10-07

## Context
The harness is what this project demonstrates. Aegis already uses LangGraph.

## Options considered
- LangChain: wraps messages, tools, loop and memory, which are exactly the parts to own.
- LangGraph: suits fixed graphs; Usta is an open-ended loop; checkpointing is covered by ADR-014.
- Own harness + libraries for plumbing.

## Decision
Write the agent logic (loop, stop reasons, budgets, tool pipeline, policy/taint, compaction, verifier, skills loader, ModelPort, approvals, persistence, evals). Use libraries for plumbing: anthropic, claude-agent-sdk, mcp, FastAPI, Pydantic, SQLAlchemy/asyncpg, LiteLLM (adapter), OpenTelemetry/Langfuse, Docker SDK, PyJWT.

## Consequences
Every line of the harness is explainable in an interview; more code to write and test.

## Revisit when
—
