# ADR-026: Skills as SKILL.md folders   (resolves D-20)
Status: accepted
Date: 2026-10-07

## Context
Reusable know-how without paying context on every turn.

## Options considered
A SKILL.md + scripts, index in prompt, body on demand; B all in system prompt; C typed tools only.

## Decision
A. Anthropic-compatible frontmatter; `skill.load` serves both engines (SDK native skills off); scripts run in sandbox from `/skills` (ro); every output skill has `check.py`; repo-versioned trusted skills only. v1: pdf-report, xlsx, docx, charts, company-glossary, email-reply-style.

## Consequences
Metric: correct skill loaded per T2 task. User-uploaded skills rejected (injection and supply-chain route).

## Revisit when
Users need their own skills (requires review flow).

## Implementation (M1)
- Frontmatter is limited to `name` and `description`; other keys are rejected.
- `check.py` contract: `python check.py <file>` prints one JSON line `{"ok": bool, "reasons": [str], "text_sample": str}`; it exits 0 when the file was checked and 2 on a usage error. It checks that the file opens, has content, and glyph coverage. The host runs `langcheck` on the PDF/DOCX `text_sample` and on the final answer.
