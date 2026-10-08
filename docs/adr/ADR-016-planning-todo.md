# ADR-016: Todo tool for planning   (resolves D-07)
Status: accepted
Date: 2026-10-07

## Context
Cowork shows a live task list. Plan-level approval was rejected in ADR-010.

## Options considered
A todo tool; B planner + executor; C plan approval; D none.

## Decision
A. Usta's own `todo` tool in both engines (SDK TodoWrite disabled), stored in run state, re-injected after compaction, rendered live. If a task looks like ≥3 steps and no todo exists by turn 2, the loop injects a reminder.

## Consequences
Same progress view for both engines; the reminder's effect is measured in T2.

## Revisit when
T2 shows poor plan discipline on long tasks.
