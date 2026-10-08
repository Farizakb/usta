# ADR-037: Milestones M0–M5 and cut line   (resolves D-38)
Status: accepted
Date: 2026-10-07

## Context
~10 h/week alongside a full-time job and a job search.

## Options considered
Blueprint v0.2 order (8 weeks) vs reordered milestones with proofs and an explicit cut line.

## Decision
M0 foundations (gVisor spike day 1) → M1 tools + sandbox → M2 MCP + web + safety → M3 two engines + context + evals → M4 UI → M5 measure + ship; stretch T-b. Cut order: VM deploy → Brave + search bake-off → third-party MCP server → context layer 2 → UI polish. Never cut: own loop, tool pipeline, MCP servers, gVisor sandbox, taint + approvals, T1/T3, engine=sdk.

## Consequences
M0–M4 ≈ 10–12 weeks; M5 +3–4 weeks.

## Revisit when
M1 not done by week 5 (start cutting).
