# AI/LLM security incidents and vulnerabilities, 2026-09-23 to 2026-10-23

Coverage note: the search tool returned very little dated inside the window. Only three items were confirmed as published in-window (MCP Python SDK OAuth advisory, GitLab Duo CVE, Symantec LLMjacking honeypot). Most other material is background. Searches for Ollama, vLLM, Hugging Face pickle, Simon Willison, and malicious-MCP-package items returned nothing dated in the window. Many sources are secondary aggregators; primary advisories were not directly checked.

## Which AI frameworks/tools had CVEs or advisories in this window?

### Takeaway
In-window: the MCP Python SDK OAuth-client issuer-validation flaw (WS-2026-0089, published 2026-09-28) and GitLab Duo Agent Platform prompt injection CVE-2026-96893 (2026-10-12). The rest is earlier 2026 background, mostly LiteLLM, LangGraph and Semantic Kernel.

### Cited Findings
- IN WINDOW, 2026-09-28 (updated 2026-10-07): WS-2026-0089, MCP Python SDK (`mcp`). The OAuth client (`mcp.client.auth`) does not always validate the authorization server issuer metadata and does not bind stored client credentials to their auth server. A malicious or compromised MCP server can redirect the client to a token endpoint it controls and receive the client secret, auth code, PKCE verifier or client assertion. CVSS v4 8.7 / v3 7.5 High, CWE-522. Affected 1.9.1-1.29.1 and 2.0.0a1-2.1.1; fixed in 1.30.0 and 2.2.0. — [Mend.io WS-2026-0089](https://www.mend.io/vulnerability-database/WS-2026-0089/)
- IN WINDOW, 2026-10-12: GitLab CVE-2026-96893, high (CVSS 3.1 7.3) prompt injection in the Duo Agent Platform; an authenticated attacker could place crafted content in agent instructions so commands run in another user's context. Fixed in the 2026-10-12 security release (version numbers not found). Credited to GitLab internal researcher Mert Coskuner. Single secondary source. — [Penligent](https://www.penligent.ai/hackinglabs/?p=7709)
- BACKGROUND (2026-05-07): Microsoft disclosed Semantic Kernel CVE-2026-26030 (Python, in-memory vector store filter passed to `eval()`, CVSS 9.8 per one source, fixed in semantic-kernel 1.39.4; .NET fixed 1.71.0) and CVE-2026-25592 (.NET, DownloadFileAsync exposed as a model-callable function allowing arbitrary file write). — [PointGuard AI](https://www.pointguardai.com/ai-security-incidents/semantic-kernel-lets-a-prompt-open-a-shell-cve-2026-25592-cve-2026-26030); Microsoft post: [When prompts become shells](https://microsoft.com/en-us/security/blog/2026/05/07/prompts-become-shells-rce-vulnerabilities-ai-agent-frameworks/)
- BACKGROUND, LiteLLM (secondary sources, unverified): CVE-2026-42208 SQLi in API-key validation, fixed 1.83.7-stable (2026-04-19), exploitation attempts reported by Sysdig within 36h; CVE-2026-42271 command injection via MCP test endpoints in 1.74.2-1.83.6, fixed 1.83.7, reportedly added to CISA KEV 2026-06-08; CVE-2026-30623 (CVSS 9.8) MCP server creation command injection, listed 2026-07-15; a further chain (CVE-2026-47101/47102/40217) reportedly affects all versions before v1.83.14-stable (CVSS 9.9). — [Wiz CVE-2026-30623](https://www.wiz.io/vulnerability-database/cve/cve-2026-30623); [CSA note on CVE-2026-42271](https://labs.cloudsecurityalliance.org/wp-content/uploads/2026/06/CSA_research_note_LiteLLM_RCE_CVE-2026-42271_20260609-csa-styled.pdf); [Rescana](https://www.rescana.com/post/critical-litellm-vulnerability-chain-enables-remote-code-execution-and-full-ai-gateway-server-takeover-cve-2026-42271-cv)
- BACKGROUND, LangChain/LangGraph (Cyera "LangDrained"): CVE-2026-34070 path traversal (7.5), CVE-2025-68664 deserialization leaking API keys (9.3), CVE-2025-67644 LangGraph SQLite checkpoint SQLi (7.3); fixed in langchain-core >=1.2.22 and langgraph-checkpoint-sqlite 3.0.1. Publication date not confirmed. — [Let's Data Science](https://letsdatascience.com/news/researchers-find-critical-vulnerabilities-in-langgraph-b381bea1)
- BACKGROUND: Starlette "BadHost" auth-bypass (CVE-2026-48710) reported to affect Python ASGI apps with path-based auth middleware, including vLLM, FastAPI and the Python MCP SDK. — same CSA/Rescana sources above.

### Inferences
- For a Python stack, the actionable items are: upgrade `mcp` to >=1.30.0 / 2.2.0 if using its OAuth client; keep LiteLLM current if used as a gateway; check Starlette version.

### Gaps
- No in-window CVEs found for LangChain, LlamaIndex, vLLM, Ollama, Ray, MLflow, transformers; this may be search-tool limitation, not absence. Check GitHub Advisory DB directly.
- GitLab fixed version numbers not found.

## Prompt-injection / agent-hijacking attacks

### Takeaway
No in-window exploited-in-the-wild prompt-injection incident was confirmed. The GitLab Duo CVE is the only in-window item.

### Cited Findings
- IN WINDOW: GitLab Duo CVE-2026-96893 (see above).
- BACKGROUND (disclosed mid-April 2026): "Comment and Control" prompt injection via PR metadata/comments hit Claude Code, Gemini CLI and GitHub Copilot agents; no CVEs assigned. — [Repello](https://repello.ai/blog/comment-and-control-claude-code-gemini-copilot-prompt-injection)
- BACKGROUND (2026-08-18): Context7 MCP server CVE-2026-75130, poisoned custom instructions could make coding agents steal credentials or delete files. — [Mend.io](https://mend.io/vulnerability-database/CVE-2026-75130/)

### Inferences
- Pattern: untrusted text (PR comments, repo instructions, tool docs) reaching an agent with shell/file tools remains the dominant vector.

### Gaps
- Nothing found for Cursor, Codex, Claude Code CVEs in window; Embrace The Red, Simon Willison, Invariant Labs posts in window not retrievable.

## MCP ecosystem incidents

### Takeaway
The only in-window MCP item is the Python SDK OAuth advisory; no new malicious-MCP-server incident was found in the window.

### Cited Findings
- IN WINDOW: WS-2026-0089 (above).
- A GBHackers page bearing a 2026-10-18 banner is actually a July 10, 2025 article on mcp-remote CVE-2025-6514 (CVSS 9.6, 0.0.5-0.1.15, fixed 0.1.16, found by JFrog); the search-snippet date was the site banner, not a new disclosure. — [GBHackers](https://gbhackers.com/critical-mcp‑remote-vulnerability/)
- BACKGROUND: typosquatted npm MCP packages flagged in OSV (June 2026); pi-exa-mcp malicious (May 2026); code-assist-mcp (Aug 2026); postmark-mcp BCC backdoor (Sept 2025); 3 malicious PyPI MCP servers with reverse shell (JFrog, Oct 2025). — [OSV MAL-2026-5484](https://osv.dev/vulnerability/MAL-2026-5484); [JFrog](https://research.jfrog.com/post/3-malicious-mcps-pypi-reverse-shell/)
- BACKGROUND: mcp-router CVE-2026-81094 (2026-08-27) exposed aggregator on open port; alibabacloud-rds-openapi-mcp-server CVE-2026-9680 (2026-07-28) bound to all interfaces. — [Mend.io](https://mend.io/vulnerability-database/CVE-2026-81094/); [CIRCL](https://cvepremium.circl.lu/vuln/CVE-2026-9680)

### Gaps
- Claims like "30 CVEs in 60 days" and "5,832 of 9,695 servers vulnerable" come from low-quality aggregators; unverified.

## Provider breaches, leaked keys, model-hub poisoning

### Takeaway
One in-window item: Symantec's LLMjacking honeypot report (2026-10-21). No in-window provider breach or model-hub poisoning found.

### Cited Findings
- IN WINDOW, 2026-10-21: Symantec Threat Hunter Team's AI honeypot captured instructions for an offensive agent that finds exposed LLM endpoints and uses them as free compute; config allowed up to 100,000 steps without human approval; planned workflow: scan, exploit, harvest credentials, deploy crypto-miners. The honeypot did not execute tool calls, so no confirmed victim success. Honeypot logged >127,000 external requests. — [Let's Data Science](https://letsdatascience.com/news/symantec-finds-autonomous-agent-hijacking-exposed-llms-to-ru-1b86bbae)
- BACKGROUND (2026-06-12 Sysdig, via CSA): attacker used a misconfigured Ollama server as the reasoning engine for a multi-stage attack; CSA also cites a March 2026 LiteLLM supply-chain compromise exposing provider credentials. — [CSA note](https://labs.cloudsecurityalliance.org/wp-content/uploads/2026/06/CSA_research_note_llmjacking_evolved_offensive_agentic_20260620-csa-styled.pdf)
- BACKGROUND (2025): nullifAI broken-pickle models bypassing Picklescan on Hugging Face (ReversingLabs); ~100 malicious models (JFrog 2024). — [Infosecurity](https://www.infosecurity-magazine.com/news/malicious-ai-models-hugging-face/)

### Gaps
- No 2026 Hugging Face pickle incident, RAG/chat-log leak, or AI provider breach found in window.
