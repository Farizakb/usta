# ADR-002: Data path to external model APIs   (resolves D-26)
Status: blocked (default assumed: all connector data is synthetic fixtures)
Date: 2026-10-07

## Context
Which company and client data may reach an external model API is a management/legal answer that doesn't exist yet. Free-tier models and Langfuse Cloud may log or train on inputs.

## Options considered
- A: all internal data to the API. B: data-class tags, some classes blocked. C: some classes routed to a local model. D: nothing client-related goes external.

## Decision
Build and evaluate on synthetic fixtures only. Data-class tags exist as a mechanism; no real company data enters any profile until approved.

## Consequences
Free tiers, Langfuse Cloud and a public repo are acceptable now. Real backends live only in a private plugin repo.

## Revisit when
Management/legal answers; then revisit ADR-022 (routing by data class), ADR-023 (local model), ADR-033 (self-hosted observability).
