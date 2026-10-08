# ADR-038: Invariants P1–P12
Status: accepted
Date: 2026-10-07

## Context
Must-hold rules need a deterministic enforcement layer, not a prompt.

## Options considered
Blueprint P1–P8 as proposed vs amended + new invariants from grilling.

## Decision
P1 sandbox no network/credentials · P2 outbound follows the verdict function · P3 unattended runs never auto-approve · P4 subscription serves only its owner · P5 ports-only dependencies, LiteLLM only in its adapter · P6 explicit stop reasons · P7 every call logged with cost, append-only, price entry required · P8 no fake/fallback/downgraded model or sandbox passes as real · P9 external writes at-most-once · P10 agent can't exceed the user's rights · P11 changed tool-description hash blocks the tool · P12 web.fetch never reaches private/loopback/link-local/metadata addresses.

## Consequences
Each has a test in T1 or T3 (SPEC §17).

## Revisit when
A new outbound channel or engine is added.
