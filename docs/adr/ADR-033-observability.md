# ADR-033: OpenTelemetry exported to Langfuse   (resolves D-34)
Status: accepted
Date: 2026-10-07

## Context
Self-hosted Langfuse v3 needs Postgres + ClickHouse + Redis + S3 (too heavy for a small VM). Langfuse Cloud Hobby is free (50k units/month, 30 days) and accepts OTLP (F10). Aegis used OTel + Jaeger.

## Options considered
A OTel + Jaeger; B Langfuse SDK in code; C OTel with GenAI conventions → Langfuse.

## Decision
C. Spans run → turn → model_call | tool_call → policy_verdict with GenAI + Usta attributes. Exporter per profile: Langfuse Cloud (dev/VM, fixtures only); self-hosted Langfuse or Jaeger when real data arrives. Eval scores pushed to Langfuse. Export failure never breaks a run.

## Consequences
Postgres audit stays source of truth; in-app run view reads Postgres.

## Revisit when
Real data arrives (ADR-002) or usage exceeds the Hobby quota.
