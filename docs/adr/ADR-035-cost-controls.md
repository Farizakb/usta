# ADR-035: Cost limits, park-and-ask, no auto-downgrade   (resolves D-35)
Status: accepted
Date: 2026-10-07

## Context
Cost efficiency is a requirement (R10); silent fallbacks are forbidden.

## Options considered
At the cap: stop / ask / downgrade model.

## Decision
Run: 40 turns, $0.50 (park + ask to continue), 20 min active time. User: $10/month. Account: Console cap $20/month and Pro SDK credit → `provider_quota`. Never auto-downgrade the model. Every stop reason explicit.

## Consequences
Cost per task visible in run view and evals. $0.50 is a guess, recalibrated after M3 to p90 × 1.5.

## Revisit when
Measured costs land (after M3).
