# ADR-034: Eval tiers, cadence, variance; SDK engine as baseline   (resolves D-32, D-33)
Status: accepted
Date: 2026-10-07

## Context
Budget: Pro SDK credit (~$20/month) + $20/month API cap. Aegis lesson: single-run deltas over small n are noise.

## Options considered
Cadence per change / milestone / nightly; 1/3/5 repeats; intervals or not; baseline via SDK, manual Cowork, or none.

## Decision
T0 once; T1 + T3a every commit on the fake model; T2 (30 tasks, ≥20 Azerbaijani) smoke on dev-free at will, full at milestones; T3b at milestones (must be 100%). Milestones 1 repeat; final README run 3 repeats per engine spread over two months; 95% Wilson intervals; no claims inside the interval. LLM judge only for T-d/T-e report quality, calibrated on 10 hand-labelled outputs (<80% agreement → indicative only). Baseline = `engine=sdk`; manual Cowork comparison dropped.

## Consequences
Results as timestamped JSON with code SHA; every failure becomes a T2/T3 case.

## Revisit when
Measured run-to-run variance differs a lot from the ±8–10 point estimate.
