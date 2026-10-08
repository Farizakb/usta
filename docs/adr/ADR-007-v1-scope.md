# ADR-007: v1 scope   (resolves D-03)
Status: accepted
Date: 2026-10-07

## Context
Every v1 feature must be core (loop, tools, MCP, sandbox) or feed a deep dive.

## Options considered
Per anchor: T-a, T-c, T-d, T-e, T-f, T-b scheduling, company writes, scanned PDFs.

## Decision
v1 = T-a, T-c, T-d, T-e (incl. `email.send`, always with approval), T-f (digital PDFs only). T-b scheduling is the first stretch item. Company-system writes and OCR/vision are v2.

## Consequences
One outbound write channel (`email.send`) plus web egress; no scheduler or unattended runs in v1 core.

## Revisit when
Core milestones finish early (add T-b).
