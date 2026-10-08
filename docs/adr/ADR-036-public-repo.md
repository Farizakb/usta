# ADR-036: One public repo with company-neutral names   (resolves D-37)
Status: accepted (manager OK pending)
Date: 2026-10-07

## Context
All data is synthetic and connectors use fixture backends; the remaining risk is employer and internal system names in a public repo.

## Options considered
A public runtime + private deployment repo; B everything private; C one public repo, neutral names, private repo only when real backends exist.

## Decision
C. Names: `ops` (installations, stock), `fleet` (Wialon-style), `company-glossary`; company described as "a telematics and security company in Azerbaijan". Real backends only ever as private plugin packages. MIT licence. gitleaks pre-commit + CI from the first commit. Ask the manager before the first public push and record the answer here.

## Consequences
BLUEPRINT.md, SPEC v0.2 history and benchmark sample sentences must be kept out or neutralized before publishing (SPEC §19).

## Revisit when
Manager says no (fall back to B).
