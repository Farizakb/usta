# ADR-017: Three-layer, cache-aware context management   (resolves D-08)
Status: accepted
Date: 2026-10-07

## Context
Core of deep dive A. Every change to earlier messages breaks the prompt cache (R10).

## Options considered
Inline/truncate/offload for results; sliding window/compaction/rolling summary for history; same or cheaper compaction model; provider-side context editing.

## Decision
Layer 1 offload (>~2k-token results to file + preview); layer 2 clear old tool results in batches (>~50% window); layer 3 structured compaction by the `light` model (>~75% window). Thresholds from `caps.context_tokens`. Prefix: system → tools (sorted) → skill index → style examples → cache marker → preferences → summary → recent turns.

## Consequences
Rejected: rolling summary (breaks cache), provider context editing (vendor tie). Deep dive A compares naive / 1+3 / 1+2+3 / sdk on success, tokens, cache hit rate, overflows.

## Revisit when
Measurements show a layer doesn't earn its complexity.
