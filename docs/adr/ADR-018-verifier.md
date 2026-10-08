# ADR-018: Verifier only, outside the engines   (resolves D-09)
Status: accepted
Date: 2026-10-07

## Context
"Done" claims need an independent check; research fan-out adds orchestration and cost.

## Options considered
A none; B verifier only; C verifier + research fan-out.

## Decision
B. Runs in Usta after the engine reports done (identical for both engines). Code checks first (skill `check.py`, language check), then an LLM check with read-only tools for what code can't judge. Reports, never fixes. One retry on fail; second fail → `verification_failed`, output shown with a warning.

## Consequences
Metric: false-done rate. Verifier on `main` vs `light` is measured. Fan-out is v2.

## Revisit when
T-d research overflows context despite ADR-017.
