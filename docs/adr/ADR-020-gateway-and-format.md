# ADR-020: Own message types; anthropic + LiteLLM + fake adapters   (resolves D-12, D-13)
Status: accepted
Date: 2026-10-07

## Context
R6 needs provider breadth; R10 needs full control of cache markers and usage on the main provider. LiteLLM was compromised on PyPI on 2026-03-24 (F8).

## Options considered
A own thin adapters only; B LiteLLM everywhere with OpenAI-shaped messages; C own types + direct Anthropic adapter + LiteLLM as one adapter.

## Decision
C. Core uses Usta message types. Adapters: `anthropic` (production), `litellm` (library mode; free tiers, local, others), `fake` (test only). Gateway wrapper outside adapters handles logging, retries, timeouts, circuit breaker, cost.

## Consequences
LiteLLM controls: exact pin + hash lock, imported only by its adapter (import-linter), adapter gets only its own key, Dependabot. Round-trip contract test per adapter incl. cache tokens.
Pinned litellm==1.102.1 on 2026-10-08 (hash-locked in uv.lock).

## Revisit when
Usta serves a team (consider LiteLLM proxy) or LiteLLM loses cache/usage fidelity.
