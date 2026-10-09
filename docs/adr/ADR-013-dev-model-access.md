# ADR-013: Dev-time model access   (resolves D-17)
Status: accepted
Date: 2026-10-07

## Context
Budget-sensitive. Subscription OAuth may only power the Agent SDK (F1); Pro includes ~$20/month SDK credit. Own loop needs an API key or another provider.

## Options considered
- A: API key for everything. Against: pays for all baseline runs.
- B: subscription for `engine=sdk`, other sources for `engine=own`.
- C: own loop through `claude -p` with text-emulated tools. Rejected: breaks parity, no native tool calls.
- D: subscription OAuth token against the API. Rejected: not permitted.

## Decision
B as a hybrid: fake model for most dev ($0); free-tier model via LiteLLM for own-loop iteration ($0, exercises R6); Pro subscription for `engine=sdk`; Anthropic API key with a $20/month Console cap for own-loop milestone evals. Company Team seat not used.

## Consequences
P4 guard (`ANTHROPIC_API_KEY` unset for `dev-sub`). Engine comparison uses token counts priced from one table. Final eval spread over two months (ADR-034).

## Revisit when
Budget increases or Pro credit terms change.

## Update 2026-10-09: chosen dev own-loop model
The dev own-loop model is `openai/gpt-6-luna` through LiteLLM (profile `dev-openai`), a user decision. OpenAI API data is not used for training by default; cost is about $0.01 per smoke. `dev-free` (Gemini free tier, $0) remains available. The rest of this decision is unchanged.
