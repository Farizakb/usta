# ADR-003: Three measured deep dives   (resolves D-39)
Status: accepted
Date: 2026-10-07

## Context
Aegis already shows a fixed LangGraph pipeline, Docker sandbox verification, deterministic policy, HITL, PGVector RAG, model tiering, tiered evals and OTel/Jaeger. Usta must show what Aegis can't.

## Options considered
A own harness vs Agent SDK; B injection defence under the lethal trifecta; C Azerbaijani; D context management; E provider-agnostic/local models; F MCP client + scheduling.

## Decision
Measure A (with D folded in), B and C. E and F are built to work, not measured. MCP, tools, the agent loop and a production-grade sandbox are the core of the project.

## Consequences
Requires a baseline engine (ADR-012). Everything outside the deep dives stays shallow on purpose.

## Revisit when
Target job postings emphasise self-hosted models (swap in E).
