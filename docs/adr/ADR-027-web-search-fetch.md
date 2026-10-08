# ADR-027: Tavily default, Brave adapter, own web.fetch with SSRF guard   (resolves D-21)
Status: accepted
Date: 2026-10-07

## Context
Tavily: 1,000 free credits/month, no card. Brave: $5 credit/month, card required, no cap (F11). Vendor server-side search bypasses Usta's pipeline and breaks URL provenance (ADR-011).

## Options considered
A SearchPort with Tavily + Brave; B Brave only; C SearXNG self-hosted.

## Decision
A. `web.fetch` is own code (httpx + HTML→Markdown) in the trusted zone: resolve DNS and block private, loopback, link-local and metadata ranges (re-check after every redirect), http/https only, ≤3 redirects, size cap, timeout; result offloaded and sets `untrusted`.

## Consequences
P12 invariant; SSRF probes in T3a. 30-query Azerbaijani comparison of Tavily vs Brave on free credits picks the default.

## Revisit when
Free tiers change or Azerbaijani result quality is poor on both.
