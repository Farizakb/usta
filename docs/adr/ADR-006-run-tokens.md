# ADR-006: Per-run delegated token   (resolves D-27)
Status: accepted
Date: 2026-10-07

## Context
"The agent can't exceed the requesting user's rights" is a safety claim tied to deep dive B. The VM deployment has multiple logins.

## Options considered
- A: shared service account. Against: over-privileged; audit says "Usta did it".
- B: Usta-signed per-run token, servers enforce scopes. For: provable; 1–2 days.
- C: full MCP OAuth 2.1. Against: days of OAuth plumbing outside the deep dives.

## Decision
B, kept small: PyJWT HS256 token with `user_id`, `scopes`, `run_id`, short TTL; Bearer for HTTP servers, env var for stdio. Local accounts with argon2 and session cookies. Scheduled runs act as their creator with scopes re-checked at start.

## Consequences
P10 invariant; T3 case for a missing scope.

## Revisit when
Real backends with their own identity providers arrive (then C).
