# ADR-028: MCP servers with swappable backends; Mailpit; seeded fixtures   (resolves D-22 details)
Status: accepted
Date: 2026-10-07

## Context
Connectors run on synthetic data (ADR-002) but must be replaceable by real systems without touching tools, tiers or evals.

## Options considered
JSON fixtures vs real protocol stand-ins; copying real APIs vs own tool schemas.

## Decision
Each server = tools layer (Usta-designed schemas) + `Backend` protocol + `FixtureBackend`. `email` uses Mailpit (real IMAP/SMTP; sent mail visible in its UI). `fixtures/generate.py` (fixed seed): ~200 installations, ~50 stock items, ~30 vehicles × 8 weeks with planted anomalies, ~40 emails incl. ~8 injection payloads; plus injection web pages and an xlsx. stdio in dev, streamable HTTP in compose; per-run token on every call. One official reference server added by config only.

## Consequences
Exact ground truth for T2; publishable data; real backends are private plugins.

## Revisit when
A real backend is approved.
