# ADR-032: No vector retrieval in v1   (resolves D-31)
Status: accepted
Date: 2026-10-07

## Context
No v1 anchor needs corpus search; Aegis already shows PGVector RAG; Azerbaijani embedder choice is unmeasured.

## Options considered
A agentic grep; B vector RAG day one; C bake-off then add.

## Decision
A. `file.search` with `az_casefold()` (İ→i, I→ı), unit-tested on pitfall words, plus `file.read`.

## Consequences
Weak for large uploaded corpora; acceptable for v1 anchors.

## Revisit when
A task needs search over >~50 documents: pgvector in the existing Postgres + bake-off (LocRet-small, BGE-M3, multilingual-e5) on 50–100 Azerbaijani queries.
