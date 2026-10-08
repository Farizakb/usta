# ADR-001: Portfolio-first goal, pilot-grade rigor   (resolves D-04, D-05)
Status: accepted
Date: 2026-10-07

## Context
Blueprint mixed two goals: learning/portfolio (R8) and a tool staff depend on (pilot, legal and IT gates). One engineer, ~10 h/week (F9). Aegis already exists as a portfolio project.

## Options considered
- Portfolio-first: build now on fixtures; company gates become BLOCKED defaults. Against: no real-user evidence.
- Staff tool first: manager, legal, IT answers before building. Against: blocks on others; scope must shrink hard.

## Decision
Usta is primarily a strong portfolio project ("simple but strong"); Fariz is the only user (D-04 option B); Usta only takes work that needs company connectors, and the README says so (D-05 option A).

## Consequences
Pilot-grade rigor (real evals, sandbox, approvals) without SSO, HA or SLAs. A real pilot is a v2 bonus.

## Revisit when
A manager asks for a pilot or real users are waiting.
