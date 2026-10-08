# ADR-011: Run-level taint + URL provenance   (resolves D-25)
Status: accepted
Date: 2026-10-07

## Context
Run-level taint is safe but parks many harmless fetches in runs that read email (T-e).

## Options considered
- A: run-level only. B: run-level + URL provenance. C: full value-level provenance. Against C: a research project.

## Decision
B. When private ∧ untrusted, `web.fetch` is allowed without asking only if the URL appeared verbatim in a `web.search` result or the user's message. URLs from fetched pages are not trusted. `web.search` queries always ask in that state.

## Consequences
~30 lines of deterministic code. Known limits become T3 cases: choice-encoding via planted literal URLs; leakage through search queries. Deep dive B result: A vs B on attack success (must be 0%) and false-park rate.

## Revisit when
T3 finds a bypass, or false-park rate stays high (consider C as a deep dive).
