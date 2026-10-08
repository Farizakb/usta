# ADR-012: Two engines behind EnginePort   (resolves D-06)
Status: accepted (supersedes the earlier "own loop only, SDK as eval script" choice)
Date: 2026-10-07

## Context
Requirement: the whole harness runs on Fariz's machine on his subscription (R7) and goes to production by config (R9). The subscription can only power the Agent SDK (F1). Deep dive A needs a baseline.

## Options considered
- Own loop only (SDK only in an eval script). Against: product can't run on the subscription.
- Agent SDK only. Against: Claude-only, hides the harness.
- LangGraph. Against: fixed graphs; already in Aegis.
- Two engines sharing everything except the turn loop.

## Decision
`engine=own` (own asyncio loop; API key or any provider) and `engine=sdk` (Agent SDK; subscription in dev or API key). Shared: UI, run store, tool pipeline, MCP, policy (SDK via PreToolUse hook), approvals, sandbox, skills, verifier, audit, evals. SDK built-ins disabled.

## Consequences
Deep dive A is a config flag. On `engine=sdk`, compaction is the SDK's and durability is best effort. P4 guard. Pro's ~$20/month SDK credit limits heavy sdk use.

## Revisit when
The SDK engine clearly beats the own loop and production needs it (then define the switch rule).
