# ADR-010: Verdict function over tier × run flags   (resolves D-24)
Status: accepted
Date: 2026-10-07

## Context
If `email.send` always asks and is the only outbound tool, taint never changes a verdict and deep dive B has nothing to measure. `web.fetch` (URL) and `web.search` (query) are exfiltration channels too. Claude Cowork uses permission-gated tool calls with "always allow".

## Options considered
- A: per-tool static rules. Against: can't tell harmless from risky fetches.
- B: tiers + run flags. C: plan-level approval. Against: plan scope not machine-checkable.

## Decision
`verdict = f(tier, private, untrusted, url_provenance, grants)`: read/local allow; egress allow unless private ∧ untrusted → ask; external_write always ask; unregistered or hash-changed → block. Approval card shows payload + taint sources. Buttons: Allow once / Allow for this run (egress, same tool + domain) / Deny. No grant outlives its run; TTL on approvals; no skip-all mode.

## Consequences
Deterministic, unit-tested. Sandbox stays network-less (stricter than Cowork's proxy allowlist).

## Revisit when
Approvals per task make users quit (consider persistent grants, v2).
