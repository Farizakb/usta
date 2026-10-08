# ADR-019: User-written preferences + knowledge as skills   (resolves D-11)
Status: accepted
Date: 2026-10-07

## Context
Agent-written memory is a persistence channel for injected instructions (memory poisoning).

## Options considered
A none; B-lite user-written preferences; B-full agent-written notes; C company knowledge as skills.

## Decision
C + B-lite. Per-user `preferences.md` edited only in the UI, injected after the cache marker. Glossary and procedures as skills. No agent-written memory in v1.

## Consequences
No poisoning surface. v2 rule if agent memory arrives: memory writes from an `untrusted` run always ask.

## Revisit when
Traces show repeated corrections the user can't capture in preferences.
