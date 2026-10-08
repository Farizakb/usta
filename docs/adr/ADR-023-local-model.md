# ADR-023: Local model as a plumbing test   (resolves D-16)
Status: accepted
Date: 2026-10-07

## Context
R6 requires local-readiness; no GPU (F9); local quality is not a deep dive.

## Options considered
A claim only; B one Ollama-on-CPU integration test; C measure local Azerbaijani quality.

## Decision
B. `local` profile: own engine, `litellm` adapter, small tool-calling model on Ollama. One `pytest -m local` test (not in CI) completes a short task with tools and sandbox. README states it proves plumbing, not quality.

## Consequences
R6 proven by a pass/fail test; no quality claims.

## Revisit when
ADR-002 requires on-prem processing or a GPU becomes available (then C as a deep dive).
