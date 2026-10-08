# ADR-022: Two static roles, main and light   (resolves D-15)
Status: accepted
Date: 2026-10-07

## Context
Aegis showed −31% cost with a cheap model for triage. Data-class routing is blocked (ADR-002).

## Options considered
A one model; B static roles; C trained router; D route by data class.

## Decision
B with two roles: `main` (agent turns, LLM verifier), `light` (compaction, titles, previews). No `hard` role. Roles set per profile; model IDs only in config; missing price entry stops startup.

## Consequences
On `engine=sdk` only `main` applies. Measured: verifier on main vs light.

## Revisit when
A v1 task needs escalation, or ADR-002 unblocks with data-class routing.
