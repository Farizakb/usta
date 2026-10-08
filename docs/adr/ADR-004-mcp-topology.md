# ADR-004: Built-ins in-process, connectors as MCP servers   (resolves D-22 protocol)
Status: accepted
Date: 2026-10-07

## Context
MCP is required for connected apps. Built-in tools (files, code_exec, web, todo) are tightly coupled to the workspace and sandbox.

## Options considered
- A: built-ins in-process, connectors as MCP servers, one tool pipeline. For: MCP where it adds value. Against: two tool kinds.
- B: everything is MCP. Against: IPC on every file call; uniformity is superficial.
- C: A + Usta as an MCP server. Against: scope.

## Decision
A. Usta builds 3 MCP servers (email, ops, fleet) and plugs in one third-party server. Every tool goes through registry → schema → policy → taint → audit → execute.

## Consequences
Tiers come from Usta config; MCP annotations are ignored for policy. Tool-description hashes are pinned (P11). Tool poisoning is in deep dive B.

## Revisit when
Another agent needs to call Usta (then C).
