# ADR-021: Minimal ModelCaps; refuse models without native tools   (resolves D-14)
Status: accepted
Date: 2026-10-07

## Context
LiteLLM brings in models that differ in window, tool calling and vision.

## Options considered
A+ small descriptor, refuse no-native-tools; B full degradation (text-emulated tools, OCR path); C separate weak-model mode.

## Decision
A+. `ModelCaps{context_tokens, max_output_tokens, prompt_cache, parallel_tool_calls, native_tools}`. `native_tools=False` → startup refuses with a clear error. No vision in v1. Reasoning controls passed through per adapter.

## Consequences
One loop path. Text-emulated tool calls rejected.

## Revisit when
A required local model lacks native tool calling.
