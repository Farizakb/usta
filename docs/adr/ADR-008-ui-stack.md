# ADR-008: FastAPI + Vite/React/TypeScript UI   (resolves D-01)
Status: accepted
Date: 2026-10-07

## Context
The demo video carries a lot of portfolio impact; frontend is not the skill being showcased.

## Options considered
- A: FastAPI + Jinja + HTMX. For: Python only. Against: less polished.
- B: FastAPI + React. For: polished. Against: two languages, build step.
- C: CLI only. D: Telegram bot.

## Decision
B, using Vite + React + TS (not Next.js: no SSR needed). Static build served by FastAPI; TS client generated from OpenAPI; designed with the `frontend-design` skill. A thin CLI shares the API.

## Consequences
Views: chat with live stream, task list, workspace files, approval inbox, run view, preferences.

## Revisit when
Server-side rendering or a public marketing site is needed.
