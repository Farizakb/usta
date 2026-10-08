# ADR-025: Typed tools at trust boundaries, code for compute   (resolves D-19)
Status: accepted
Date: 2026-10-07

## Context
Typed tools are reliable; code covers the long tail. Policy must see anything crossing a trust boundary.

## Options considered
A typed for everything; B code-first; C-lite fixed typed set + code_exec + manual promotion.

## Decision
C-lite with 18 tools: file.list/read/search/write, code_exec, web.search/fetch, todo, skill.load, ask_user, email.list/read/draft/send, ops.installations/stock, fleet.units/fuel_report (+ one third-party server). `ask_user` parks like an approval. `email.draft` is local.

## Consequences
Promotion rule: code_exec patterns seen in ≥3 tasks become candidate typed tools, decided manually at milestones.

## Revisit when
Tool count approaches ~20 visible tools (consider per-task tool subsets).
