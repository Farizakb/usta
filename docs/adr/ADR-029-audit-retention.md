# ADR-029: Append-only audit with retention and redaction   (resolves D-28)
Status: accepted
Date: 2026-10-07

## Context
Every model call must be logged (global rule, P7); privacy matters once real data arrives.

## Options considered
A everything forever; B everything + retention + redaction; C metadata only.

## Decision
B. Postgres is the source of truth: `model_calls`, `tool_calls`, `policy_verdicts`, `approvals`, `run_events`. App DB role has only INSERT + SELECT on audit tables; `usta_purge` role deletes. `retention_days` per profile (dev unlimited, prod 90); `usta purge` CLI. `Redactor` on writes (no-op in dev; prod masks emails, phones, plates). Live context never redacted. Observability tools get a copy.

## Consequences
Append-only enforced by the database, not convention.

## Revisit when
Company retention policy exists.
