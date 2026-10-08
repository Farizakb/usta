# ADR-009: Per-user server workspace   (resolves D-02)
Status: accepted
Date: 2026-10-07

## Context
Where files live and what sandboxed code can see is a security decision.

## Options considered
- A: per-user workspace; sandbox gets `/workspace` read-only and run `/out` read-write.
- B: sandbox sees only declared inputs. Against: friction and extra code paths.
- C: company drive connector. Against: permissions, sync, real systems.

## Decision
A. `workspaces/{user}/files/` and `workspaces/{user}/runs/{run_id}/out/`. Outputs are promoted to `files/` by the user. Uploads set the `untrusted` flag.

## Consequences
Sandbox code can read the user's own files but not modify them or send them anywhere (no network); data leaves only through policy-checked tools.

## Revisit when
Real company drive integration (C, v2).
