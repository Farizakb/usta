# Defensive guidance for Python backend / AI-LLM engineers (as of Oct 2026)

Research scope note: ~15 tool calls. Several topics were covered only by secondary sources (flagged). Not covered with primary sources: pip-audit/osv-scanner specifics, Sigstore/SLSA/Scorecard details, CISA Secure by Design, NIST AI RMF, secret-scanning tools, GPAI obligations. Those are listed under Gaps.

## 1. Python dependency / supply-chain hygiene (what do PyPA/PSF/OpenSSF/GitHub recommend, what changed in 2026, tooling)

### Takeaway
The 2026 consensus control set: lockfile with hashes, a dependency cooldown (about 7 days), Trusted Publishing with attestations on the publishing side, and SHA-pinned, least-privilege GitHub Actions. Cooldowns are now built into uv, pip, Poetry and npm. Every 2026 AI-library incident below was caught within hours, which is why cooldowns are the highest-leverage consumer control.

### Cited Findings
- uv `exclude-newer` accepts a relative duration (uv 0.9.17, Dec 2025), plus per-package override `exclude-newer-package` — [Nesbitt, Mar 2026](https://nesbitt.io/2026/03/04/package-managers-need-to-cool-down) (via search summary)
- Config: `[tool.uv] exclude-newer = "7 days"` in pyproject.toml; recorded in uv.lock; window only moves on fresh resolution (`uv lock --upgrade`, `uv add`); private indexes without upload dates need `exclude-newer = false` on that index — [pydevtools](https://pydevtools.com/handbook/explanation/what-is-a-dependency-cooldown/). Sources disagree on whether lock stores a span or a timestamp — pydevtools vs a later version of same page (per search summary).
- pip added `--uploaded-prior-to` (26.0) and relative durations (26.1); npm `min-release-age` 11.10.0 (Feb 2026); Poetry 2.4.0 `solver.min-release-age` — [Nesbitt](https://nesbitt.io/2026/03/04/package-managers-need-to-cool-down) (secondary summary; verify exact syntax in each tool's docs)
- uv docs recommend aligning Renovate `minimumReleaseAge` with uv's setting — [uv Renovate guide](https://docs.astral.sh/uv/guides/integration/renovate/index.md)
- Cooldown guidance: 7 days common default, 30 days for production/internal tooling; Dependabot lets security patches through immediately while delaying routine updates (3 days default); malicious uploads usually pulled within hours (Axios ~3h, s1ngularity ~4h); Datadog suggests 7 days, 12 hours as aggressive floor; cooldown does not detect malware and does not cover sdist build-time code — [pydevtools](https://pydevtools.com/handbook/explanation/what-is-a-dependency-cooldown/)
- PEP 740 attestations are GA on PyPI; projects using Trusted Publishing with the canonical GitHub Action (pypa/gh-action-pypi-publish) produce attestations by default; Sigstore-backed — [Sigstore blog](https://blog.sigstore.dev/pypi-attestations-ga/), [PEP 740](https://peps.python.org/pep-0740). Adoption was low at launch (~5% of top 360 projects); current adoption figure not found.
- Trusted Publishing providers expanded beyond GitHub to GitLab CI/CD, Google Cloud, ActiveState — [PyPI blog](https://blog.pypi.org/author/di/) (via search summary)
- `pylock.toml` (PEP 751 lockfile standard) can include attestation info — [pydevtools](https://pydevtools.com/handbook/explanation/why-pylock-toml-includes-digital-attestations/) (title only; content not fetched)
- GitHub Actions 2026 security roadmap (Mar 26, 2026): planned workflow `dependencies:` section locking direct and transitive action deps to commit SHAs with hash-mismatch failing the run; scoped secrets; immutable releases (Aug 2025) — [GitHub blog](https://github.blog/2026-03-26-whats-coming-to-our-github-actions-2026-security-roadmap/). Timeline (preview 3-6 months out) is third-party and unverified. Org/enterprise policy can block actions and require SHA pinning — [GitHub changelog 2025-08-15](https://github.blog/changelog/2025-08-15-github-actions-policy-now-supports-blocking-and-sha-pinning-actions/)
- npm worm lessons (relevant by analogy; Python's PyPI equivalent is token theft then republish): GitHub moved to 2FA for local publishing, 7-day token lifetimes, promoting trusted publishing — [Shai-Hulud coverage via ADT/javapro](https://javapro.io/2025/10/02/the-shai-hulud-npm-worm-when-supply-chains-bite-back/) (secondary)
- 2026 Python AI-library incidents (all vendor write-ups, single-source details):
  - LiteLLM 1.82.7/1.82.8, 2026-03-24: malicious releases via the maintainer's stolen PyPI publishing credentials; payload in a `.pth` file (runs at every interpreter start, no import needed); stole cloud tokens and SSH keys; live ~3h. Mitigations named: exact pins + hash checks, audit `.pth`/post-install behavior, rotate all creds if installed in window — [CSO Online](https://www.csoonline.com/article/4206245). How creds were stolen was not stated.
  - Guardrails AI 0.10.1 (CVE-2026-45758), 2026-05-11, fixed 0.10.2, rotate credentials; detected ~2h — [NVD](https://nvd.nist.gov/vuln/detail/cve-2026-45758), [Gurucul](https://gurucul.com/blog/malicious-payload-delivery-discovered-in-guardrails-ai-pypi-package/)
  - mistralai 2.4.6, 2026-05-12: unpublished release appeared on PyPI, executed on import, harvested credentials, quarantined within hours; attributed by Root.io to "TeamPCP"/"Mini Shai-Hulud" — [Root.io](https://www.root.io/malicious-packages/mistralai-pypi-compromise)
  - PyTorch Lightning 2.6.2/2.6.3 (late Apr 2026) credential-stealing malware tied to a malicious workflow file — [CSO Online](https://www.csoonline.com/article/4206245)

### Inferences
- Prioritized controls (my ranking by incident coverage): (1) cooldown of 7 days in uv (`exclude-newer`) and Renovate/Dependabot; would have avoided LiteLLM (3h), Guardrails (2h), mistralai (hours). (2) Hash-pinned lockfile (`uv.lock`, or `uv export` + `pip install --require-hashes`) so installs never float to a new release. (3) Maintainer side: Trusted Publishing (OIDC, no long-lived PyPI token) + phishing-resistant 2FA, since the incidents all used stolen publish credentials. (4) SHA-pin all Actions; minimal `permissions:` on GITHUB_TOKEN; separate publish job with environment protection. (5) Vulnerability scanning (pip-audit/osv-scanner/`uv audit`) catches known CVEs but would not catch these zero-day malware cases, so it ranks lower for this incident class.
- `.pth` execution means "I never imported it" is no defense; treat any install in the window as compromise and rotate.
- Trusted Publishing would not stop a compromise where attacker controls the CI workflow itself (PyTorch Lightning workflow-file case) — attestations prove provenance, not benignness.

### Gaps
- No primary source fetched for pip-audit, osv-scanner, Sigstore, SLSA, OpenSSF Scorecard, SBOM (CycloneDX/SPDX) recommendations, PyPI's own 2026 policy changes (e.g., organization accounts, token expiry), or `uv audit` details (mentioned only in pydevtools).
- Exact root causes for Mistral and Guardrails compromises not established.
- Current PEP 740 adoption percentage not found.

## 2. Secrets management and token hygiene

### Takeaway
Every incident above monetized stolen long-lived credentials (PyPI tokens, cloud keys, SSH keys). Replace long-lived tokens with OIDC-issued short-lived ones and assume anything on a dev machine/CI runner that installed a bad package is exposed.

### Cited Findings
- Trusted Publishing removes API tokens from build pipelines; GitHub's npm response shortened token lifetimes to 7 days and required stronger 2FA — [javapro summary](https://javapro.io/2025/10/02/the-shai-hulud-npm-worm-when-supply-chains-bite-back/)
- GitHub Actions roadmap adds secrets scoped to specific repos/branches — [GitHub blog](https://github.blog/2026-03-26-whats-coming-to-our-github-actions-2026-security-roadmap/)
- Post-incident guidance: rotate every credential the affected environment could reach and review cloud audit logs — [CSO Online](https://www.csoonline.com/article/4206245), [NVD CVE-2026-45758](https://nvd.nist.gov/vuln/detail/cve-2026-45758)
- MCP spec: servers must not accept tokens not issued to them (no token passthrough); use progressive least-privilege scopes, avoid wildcard scopes, log elevation events — [MCP security best practices](https://modelcontextprotocol.io/specification/draft/basic/security_best_practices)
- MCP SSRF: block private/link-local ranges incl. 169.254.169.254 cloud metadata, do not hand-roll IP validation, consider egress proxy (Smokescreen) — same MCP page

### Inferences
- Concrete for an individual: keep secrets out of `.env` files in repos that agents/package installs can read; use short-lived cloud creds (SSO/`aws sso`, workload identity) locally; use OIDC in CI; enable secret scanning/push protection (GitHub native, gitleaks, trufflehog). Tooling names here are from general knowledge, not sourced.

### Gaps
- No sourced material on secret-scanning tools, GitHub push protection, or credential-manager recommendations.

## 3. LLM application and agent security

### Takeaway
OWASP's LLM Top 10 (2025) remains the base list; the OWASP Top 10 for Agentic Applications 2026 (Dec 9, 2025) is the new companion for tool-using agents. MCP guidance has moved to OAuth-centred requirements plus local-server sandboxing. Model loading: prefer safetensors; pickle remains dangerous even with `weights_only` and scanners.

### Cited Findings
- OWASP LLM Top 10 2025: LLM01 Prompt Injection, 02 Sensitive Information Disclosure, 03 Supply Chain, 04 Data and Model Poisoning, 05 Improper Output Handling, 06 Excessive Agency, 07 System Prompt Leakage, 08 Vector and Embedding Weaknesses, 09 Misinformation, 10 Unbounded Consumption — [OWASP GenAI](https://genai.owasp.org/llm-top-10/)
- OWASP Top 10 for Agentic Applications 2026 (released 2025-12-09, 100+ contributors): ASI01 Agent Goal Hijack, 02 Tool Misuse & Exploitation, 03 Identity & Privilege Abuse, 04 Agentic Supply Chain, 05 Unexpected Code Execution, 06 Memory & Context Poisoning, 07 Insecure Inter-Agent Communication, 08 Cascading Failures, 09 Human-Agent Trust Exploitation, 10 Rogue Agents — names/descriptions from [Cycode summary](https://cycode.com/blog/owasp-top-10-agentic-applications/) (OWASP's own page did not render the list); release facts: [OWASP](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026). OWASP guidance: use alongside the LLM list when agents use third-party tools; plain chatbot/RAG is covered by the LLM list — [Modulos summary](https://docs.modulos.ai/frameworks/owasp-top-10-agentic) (secondary).
- Incidents cited as inputs to the agentic list: EchoLeak zero-click exfiltration (CVE-2025-32711), Replit agent deleting a production DB during a code freeze — [Cycode](https://cycode.com/blog/owasp-top-10-agentic-applications/)
- MCP security best practices (official, draft spec page fetched): confused-deputy (proxy servers MUST do per-client consent, exact redirect_uri match, state validation); token passthrough forbidden; SSRF mitigations; state-handle hijacking (stateless MCP; do not treat handle possession as auth; bind to verified user); local MCP servers: show exact command before one-click install, sandbox with minimal privileges, prefer stdio or restricted sockets; OAuth URL scheme validation (http/https only, no shell to open URLs); mix-up attack mitigation via issuer validation; scope minimization — [MCP spec](https://modelcontextprotocol.io/specification/draft/basic/security_best_practices). Note: the draft page replaced session hijacking with "state handle hijacking" and refers to 2025-11-25 as the prior version; the latest released version was reported as 2025-11-25 with OAuth 2.1 for remote servers — [CSA](https://labs.cloudsecurityalliance.org/agentic/agentic-mcp-security-best-practices-v1/) (secondary).
- Model loading: `torch.load` default `weights_only=True` since PyTorch 2.6; `weights_only` unpickler flaw CVE-2026-24747 fixed in 2.10.0 (CVSS 8.8); picklescan bypasses exist (PYSEC-2026-2873, GHSA-769v-p64c-89pr); lmdeploy called `torch.load()` unsafely (CVE-2025-67729); safetensors avoids code execution by design — [PyTorch dev-discuss](https://dev-discuss.pytorch.org/t/bc-breaking-change-torch-load-is-being-flipped-to-use-weights-only-true-by-default-in-the-nightlies-after-137602/2573), [NVD CVE-2026-24747](https://nvd.nist.gov/vuln/detail/CVE-2026-24747), [OSV PYSEC-2026-2873](https://osv.dev/vulnerability/PYSEC-2026-2873), [OSV GHSA-769v-p64c-89pr](https://osv.dev/vulnerability/GHSA-769v-p64c-89pr), [Corgea CVE-2025-67729](https://corgea.com/advisories/vulnerabilities/CVE-2025-67729)

### Inferences
- Prompt injection has no complete fix; design for it: least privilege per tool, no ambient credentials in the agent process, human approval for irreversible/exfiltrating actions, treat model output as untrusted input (parameterize SQL, no `eval`/`shell=True`, escape HTML), run generated code in a container/microVM without network or secrets, allowlist egress, log every tool call with arguments. These map to LLM05/LLM06/ASI02/ASI03/ASI05 but the specific remediation list is my synthesis, not a single cited source.
- Python tooling: safetensors format, `torch.load(weights_only=True)` on >=2.10, `transformers` with `use_safetensors=True`, MCP Python SDK with OAuth, an egress proxy for SSRF. (General knowledge; not individually sourced.)

### Gaps
- No primary source on prompt-injection defense patterns (e.g., spotlighting, dual-LLM, CaMeL), output-handling libraries, or LLM logging/monitoring standards.
- OWASP's ASI list not read from the OWASP page itself.
- Exact current MCP spec release (2025-11-25 vs a newer one) not verified from the official site.

## 4. Safe use of AI coding agents on developer machines

### Takeaway
2026 saw repeated prompt-injection-to-RCE and sandbox-escape CVEs in mainstream coding agents. Treat repo content, PR text, MCP servers and web results as attacker-controlled; do not rely on the agent's built-in sandbox as the only boundary.

### Cited Findings
- Cursor "DuneSlide" CVE-2026-50548 / -50549 (CVSS 9.8 v3.1): sandbox write access to a model-alterable working directory, and symlink canonicalization fallback; triggered via prompt injection from MCP/web content; fixed in Cursor 3.0. Disclosure date conflicts between sources (April 2 vs July 1, 2026) — [Wiz](https://www.wiz.io/vulnerability-database/cve/cve-2026-50548), [PointGuard](https://www.pointguardai.com/ai-security-incidents/duneslide-turns-cursor-prompts-into-sandbox-escapes-cve-2026-50548-cve-2026-50549)
- Pillar Security: sandbox bypasses in Cursor, OpenAI Codex, Gemini CLI, Antigravity by writing a file a trusted out-of-sandbox tool later loads — [BleepingComputer](https://www.bleepingcomputer.com/news/security/cursor-codex-gemini-cli-antigravity-hit-by-sandbox-escapes/)
- "Comment and Control": PR title/body prompt injection against Claude Code, Gemini CLI, Copilot running in GitHub Actions, notably with `pull_request_target` exposing secrets — [Daniel Vaughan roundup](https://codex.danielvaughan.com/2026/05/02/spring-2026-ai-coding-agent-vulnerabilities-cursor-rce-comment-control-codex-cli-defence/) (secondary blog)
- Cursor CVE-2026-26268 bare-git RCE (late Apr 2026) — same roundup (secondary)
- MCP spec: local servers run with client privileges; require consent showing the exact command; sandbox with minimal FS/network — [MCP spec](https://modelcontextprotocol.io/specification/draft/basic/security_best_practices)
- Note from the Shai-Hulud variants: Feb 2026 wave used typosquats impersonating AI developer tools — [CSA note](https://labs.cloudsecurityalliance.org/research/csa-research-note-shai-hulud-npm-worm-ai-developer-supply-ch/) (secondary)

### Inferences
- Practical: keep agents on default-ask permissions, deny reads of `~/.ssh`, cloud credential dirs and `.env`; run agents in a devcontainer/VM or separate OS user with no long-lived creds; open untrusted repos with hooks/MCP auto-start disabled; keep agent software updated (the fixes above shipped as patches); never run agents with secrets in `pull_request_target`/public-PR workflows; pin MCP servers by version and read their commands. Specific Claude Code settings were not researched (no source).

### Gaps
- No vendor-primary guidance (Anthropic, OpenAI, Cursor docs) fetched on permission models or sandboxing; no sourced guidance on `.claude`/hooks/config-file injection vectors.

## 5. Regulatory and standards updates affecting individual engineers

### Takeaway
Mostly deadline shifts. CRA vulnerability reporting for manufacturers started 2026-09-11; AI Act high-risk obligations are being delayed by the Digital Omnibus (political deal, formal adoption unconfirmed); NIST SSDF 1.2 was still a draft in the sources found.

### Cited Findings
- EU CRA Article 14 reporting applies from 2026-09-11: actively exploited vulnerabilities and severe incidents; 24h early warning, 72h notification, 14 days after fix for final report (1 month for incidents). Open-source "stewards" get a lighter regime with main duties from 2027-12-11. A CSA note says the Single Reporting Platform URL was not yet public as of 2026-09-08 (single secondary source) — [HeroDevs](https://www.herodevs.com/eu-cyber-resilience-acts), [Noze](https://www.noze.it/en/insights/cyber-resilience-act-sbom/), [CSA note](https://labs.cloudsecurityalliance.org/wp-content/uploads/2026/09/CSA_research_note_eu_cra_vulnerability_reporting_20260910-csa-styled.pdf)
- EU AI Act Digital Omnibus provisional agreement (May 2026): Annex III high-risk obligations to 2027-12-02, Annex I embedded products to 2028-08-02; Article 50 transparency largely on original schedule; needed formal adoption before 2026-08-02 — not confirmed — [Gibson Dunn](https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/)
- NIST SP 800-218r1 (SSDF 1.2) initial public draft 2025-12-17, comments to 2026-01-30, adds PO.6 and PS.4; final targeted 2026-03-31 under an executive order but not confirmed published; SP 800-218A (July 2024) is the generative-AI community profile — [NIST CSRC](https://csrc.nist.gov/News/2025/draft-ssdf-version-1-2), [NIST slides May 2026](https://csrc.nist.gov/csrc/media/presentations/2026/ssdf-and-devsecops-project/1.5a-ssdf_update-booth.pdf)

### Inferences
- For an individual contributor these matter only if employer ships a product with digital elements in the EU or builds a high-risk AI system; practical carry-over is keeping SBOMs and a vulnerability-handling path. Hobby/non-commercial OSS is generally outside CRA manufacturer duties (not verified against the regulation text).

### Gaps
- Whether the Omnibus was published in the Official Journal; GPAI obligations status; NIST AI RMF 2026 changes; CISA Secure by Design updates; OpenSSF/CISA SBOM minimum-element updates — none found.

## Which controls address the most common 2025-2026 incident patterns (summary, my synthesis)

| Pattern (sourced above) | Highest-value controls |
|---|---|
| Stolen maintainer creds, malicious release live hours | 7-day cooldown; hash-pinned lock; rotate creds after exposure |
| Auto-exec at install/startup (.pth, postinstall) | Cooldown, pins, run installs/CI without secrets, sandbox dev env |
| Workflow/CI compromise | SHA-pinned actions, minimal `permissions`, no secrets to untrusted PRs |
| Prompt injection to RCE in coding agents | Update agents, container/VM, deny secret paths, approval on side effects |
| Malicious model files | safetensors, `weights_only=True`, PyTorch >= 2.10, do not trust picklescan |
