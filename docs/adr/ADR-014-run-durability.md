# ADR-014: Postgres + in-process worker, checkpoint per step   (resolves D-10)
Status: accepted
Date: 2026-10-07

## Context
Real need: runs parked for approval may wait hours; restarts must not lose them or send an email twice. Scheduling is stretch, so no queue workload yet.

## Options considered
A in-memory; B SQLite + worker; C Postgres + in-process worker; D Postgres + Arq/Celery; E Temporal.

## Decision
C. Rules: (1) checkpoint after every step; (2) parked runs are DB rows; (3) `running` runs resume on startup; (4) `intent`/`done` records around `email.send`, unknown outcome parks and asks; (5) `engine=sdk` best effort (`interrupted` + SDK session resume).

## Consequences
Postgres needed in dev (compose in WSL2). P9 invariant with a T1 crash test.

## Revisit when
Scheduled or multi-user load needs a separate worker (then D).
