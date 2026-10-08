# ADR-031: Deterministic output-language check   (resolves D-30)
Status: accepted
Date: 2026-10-07

## Context
Main risk is drift into Turkish; prompts alone don't notice.

## Options considered
A prompt only; B deterministic check; C B + retry; D B + glossary from traces.

## Decision
B, with C's retry via the verifier and D done manually. `langcheck`: lingua-py (az/tr/en/ru) + Azerbaijani signal (`ə`, frequent x/q); skip < ~15 words. Expected language: user's language for chat/reports; customer's language for reply drafts.

## Consequences
The check's own accuracy is measured in T0 on ~100 labelled texts before it is used to measure drift.

## Revisit when
Drift rate exceeds an agreed threshold after M3.
