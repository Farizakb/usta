# Backend-stack CVEs and breaches, 2026-09-23 to 2026-10-23

Method note: ~14 tool calls. Primary pages fetched: Django weblog, python.org 3.14.8, OpenSSL advisories, postgresql.org news, CISA KEV catalog (pages 1 and 2 only). CVSS scores were rarely available from primary pages (Django, OpenSSL, python.org publish severity labels, not CVSS); a "CVSS n/a" means not found. WebFetch output is model-summarised, so re-check critical IDs against NVD before quoting.

## (a) Python and Python library CVEs with security releases in the window

### Takeaway
CPython shipped an expedited security release 3.14.8 on 2026-09-30; Django shipped 6.1.2/6.0.9/5.2.18 on 2026-10-06 (all Moderate or Low); Starlette's "BadHost" auth bypass was added to KEV on 2026-09-02 (just before the window, still relevant). Coverage of Flask/Werkzeug, urllib3, aiohttp, Pydantic, SQLAlchemy, Celery, Jinja2, cryptography, PyYAML, Pillow, uvicorn/gunicorn is a gap: no in-window advisories were found, which is not proof there were none.

### Cited Findings
- CPython 3.14.8, released 2026-09-30, "expedited security release". Fixes: CVE-2026-19445 (use-after-free in server-side SSLContext when sni_callback switches contexts), CVE-2026-19553 (SSLContext.wrap_bio() lacks server_hostname validation), CVE-2026-15310 (zipfile memory exhaustion in bzip2/LZMA/Zstandard decompression), CVE-2026-19672 (tarfile extraction filter bypass, directories created outside destination), CVE-2026-15806 (urllib.request.HTTPPasswordMgr can send credentials for one URL scheme over another), CVE-2026-17084 (StringPrep applies codepoint attributes beyond Unicode 3.2.0). Also bundled Expat updated to 2.8.5 and bundled OpenSSL to 3.5.9 (Windows/macOS/Android/iOS builds). CVSS n/a. Exploitation status not stated. Remediation: upgrade to 3.14.8. — [python.org 3.14.8](https://www.python.org/downloads/release/python-3148/)
- Same page: Python 3.14 is not affected by CVE-2026-82049 (tarfile hard link to symlink), which is fixed in the 3.10-3.13 lines (exact patch versions not captured). — [python.org 3.14.8](https://www.python.org/downloads/release/python-3148/)
- Fedora 43 shipped Python 3.14.8 on 2026-10-14 (lists CVE-2026-19553), showing distro lag of about two weeks. — [Fedora advisory via linuxsecurity](https://linuxsecurity.com/advisories/fedora/fedora-python3-14-2026-a3da6bb5cd) (secondary; date taken from search summary)
- Django security releases 2026-10-06: fixed in 6.1.2, 6.0.9, 5.2.18 (affected: main, 6.1, 6.0, 5.2). CVE-2026-77050 (Low; DoS via long language codes cached in get_supported_language_variant()); CVE-2026-84429 (Moderate; quadratic-time parse_header_parameters(), DoS via Accept/Content-Type headers); CVE-2026-87890 (Moderate; request forgery/SSRF-like: raster bytes with a VRT document make GDAL issue network requests as the Django process; fix is backward-incompatible, bytes must be wrapped in GDALRaster); CVE-2026-87975 (Moderate; model formsets let forged POST delete instances outside the limiting queryset or create instances in edit-only formsets when PK is settable via the form; default BigAutoField models not affected). Also hardens the earlier CVE-2026-15830 fix (nested geometry collections), no new CVE. No exploitation reported. CVSS n/a. — [Django weblog](https://www.djangoproject.com/weblog/2026/oct/06/security-releases/)
- Background, Starlette (FastAPI dependency): CVE-2026-48710 "BadHost" Host-header authentication bypass in Starlette before 1.0.1; added to CISA KEV 2026-09-02 (before window); maintainers rate CVSS 6.5, X41 D-Sec rates 7.0. Sources disagree on exact fixed version (1.0.1 vs 1.1.0 for some FastAPI pins). — [CSO Online](https://www.csoonline.com/article/4177711/fastapi-based-ai-tools-exposed-to-authentication-bypass-by-flaw-in-starlette-framework.html); [Belgian CCB](https://ccb.belgium.be/advisories/warning-vulnerability-starlette-framework-and-related-frameworks-fastapi-exposes); [Ionix](https://www.ionix.io/threat-center/cve-2026-48710/)
- Background, Starlette: CVE-2026-54283 (DoS, urlencoded parser path lacks multipart limits; affects 0.4.1 to before 1.3.1); CVE-2026-54282 (request.url.hostname spoofing, before 1.3.0, CVSS 3.1 3.7). Dates not established, likely before or at window start. — [SentinelOne](https://www.sentinelone.com/vulnerability-database/cve-2026-54283/); [cyberattack.ai](https://cyberattack.ai/vulnerabilities/cve-2026-54282)
- Background: Django 2026-03-03 security release (4.2.29, 5.2.12, 6.0.3) — [Canadian Cyber Centre AV26-193](https://www.cyber.gc.ca/fr/alertes-avis/bulletin-securite-django-av26-193)

### Inferences
- The Django CVE-2026-87890 (GDAL VRT network fetch) is an SSRF-class bug relevant only to GeoDjango users; CVE-2026-87975 matters to anyone using model formsets with non-default PKs.
- Starlette versions pinned transitively by FastAPI should be checked with `pip show starlette` (BadHost, DoS and hostname issues all land in Starlette, not FastAPI).

### Gaps
- No in-window advisories found for Flask/Werkzeug, urllib3, requests, httpx, aiohttp, Pydantic, SQLAlchemy, Celery, Jinja2, cryptography, PyYAML, Pillow, uvicorn, gunicorn. Only one broad search was run for these; GitHub advisory DB / OSV.dev were not queried.
- CVSS vectors for CPython and Django CVEs not obtained. Python 3.10-3.13 fixed patch versions not captured.

## (b) Backend infrastructure vulnerabilities

### Takeaway
OpenSSL published 14 advisories on 2026-09-29 (one High, rest Moderate/Low). PostgreSQL core had no dated security release in the window; the related PgBouncer 1.26.1 (auth bypass) and JDBC/psqlODBC fixes landed 2026-10-09 to 10-14. Redis, RabbitMQ, Nginx, Linux kernel, Docker/containerd/runc, Kubernetes and cloud bulletins were not researched (gap).

### Cited Findings
- OpenSSL, 2026-09-29, fixed in 4.0.3, 3.6.5, 3.5.9, 3.4.8, 3.0.23, 1.1.1zj, 1.0.2zs (per-CVE availability varies). Only High: CVE-2026-84782, DTLS retransmits handshake data from a stale buffer offset (affects 4.0, 3.6, 3.5, 3.4, 3.0, 1.1.1, 1.0.2). Moderate: CVE-2026-84783 (use-after-free in X.509 extension cache under concurrent use, 4.0 only). Low (12): CVE-2026-35189, -35191, -42772, -54872, -54873, -54875, -72897, -75804, -75805, -75806, -77696, -84784 (mostly QUIC resource exhaustion, EC/SM2 timing side channels, CMP NULL deref, DTLS record handling, SSL_set_SSL_CTX out-of-bounds). Only the first 100k of ~430k characters of the page was read, so more advisories could exist. CVSS n/a; exploitation not stated. Remediation: upgrade to the fixed version for your branch. — [OpenSSL vulnerabilities](https://openssl-library.org/news/vulnerabilities/); corroborated by [Canadian Cyber Centre AV26-980](https://www.cyber.gc.ca/fr/alertes-avis/bulletin-securite-openssl-av26-980)
- PgBouncer 1.26.1, 2026-10-14, fixes three CVEs including CVE-2026-107350 (authentication bypass); other two not captured. — [postgresql.org news](https://www.postgresql.org/about/newsarchive/-/20261014/)
- psqlODBC 18.00.0005, 2026-10-14, security fix CVE-2026-109448. — [postgresql.org news](https://www.postgresql.org/about/newsarchive/-/20261014/)
- PostgreSQL JDBC 42.7.14, posted 2026-10-09 (announcement dated 10-07), CVE-2026-107314 plus GHSA-rhp9-mr79-r74h; list may be truncated. — [postgresql.org news](https://www.postgresql.org/about/newsarchive/-/20261014/)
- PostgreSQL 19 RC 1 released 2026-10-15 (no CVEs listed). Latest core security release visible in search was 2026-02-26 (18.3, 17.9, 16.13, 15.17, 14.22). — [postgresql.org news](https://www.postgresql.org/about/newsarchive/-/20261014/); [security archive 2026-02-26](https://www.postgresql.org/about/newsarchive/security/20260226/)
- Third-party tracker lists open Postgres issues dated 2026-10-09 (SCRAM iteration-count discrepancy enabling user enumeration in 16-18; RLS cache invalidation bug); unverified against postgresql.org. — [Determinate Systems](https://security.determinate.systems/cves/status/open?page=2)

### Inferences
- A PgBouncer auth bypass is directly relevant to Python apps behind a connection pooler; treat as priority patch, but confirm CVSS and affected versions on the PgBouncer advisory first.

### Gaps
- Not researched: Redis, RabbitMQ, Nginx, Linux kernel, Docker/containerd/runc, Kubernetes, cloud provider bulletins. A mid-search result mentioned self-managed GitLab critical flaws (linuxsecurity headline) but was not verified.
- Whether PostgreSQL 18.4/17.10 (cited by a vulnerability aggregator with CVE-2026-6472..6479, -6637) exist or when they shipped is unverified.

## (c) CISA KEV additions relevant to backend developers

### Takeaway
Roughly 38 KEV entries added 2026-09-21 to 2026-10-20 were seen (two catalog pages; entries on 2026-10-21 to 10-23 may be missing). Mostly network appliances and enterprise products. Closest to backend dev stacks: Starlette BadHost (09-02, background), Apache Struts, Strapi, WordPress core, Atlassian, Citrix NetScaler.

### Cited Findings (date added to KEV)
- 2026-10-20: Siemens Software Center CVE-2026-110936; Plex Media Server CVE-2026-96652, -96654, -96655, -96656; EG Secure Solutions SiteGuard CVE-2026-106931
- 2026-10-16: Fortinet multiple CVE-2025-61624; BeyondTrust Remote Support CVE-2026-102764
- 2026-10-15: Atlassian multiple CVE-2026-21589
- 2026-10-14: Palo Alto PAN-OS CVE-2026-0322; Cisco Secure Email Gateway CVE-2026-76519; Ahsay AhsayCBS CVE-2026-105133, -105134
- 2026-10-13: Microsoft Windows CVE-2026-96951; Ivanti Connect Secure CVE-2026-104935
- 2026-10-08 (old bugs re-added, i.e. now exploited): ProFTPD CVE-2015-3306; ONLYOFFICE Docs CVE-2021-3199; Strapi CVE-2023-22894; Apache Struts CVE-2016-3081; ISC BIND CVE-2015-5477
- 2026-10-04: Citrix NetScaler CVE-2026-88779. 10-02: Zammad CVE-2026-102489, -102490. 10-01: Fortinet FortiMail CVE-2026-104286. 09-30: Cisco Catalyst SD-WAN Manager CVE-2026-76504. 09-29: Apple CVE-2026-86950. 09-27: Citrix NetScaler CVE-2026-88771, -88772. 09-25: WordPress core CVE-2026-87902; Microsoft SharePoint CVE-2026-65660; MikroTik RouterOS CVE-2026-67279. 09-24: Adobe Commerce/Magento CVE-2026-71362; WSO2 CVE-2026-5430.
- Source for all: [CISA KEV catalog](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) (pages 1 and 2 as summarised). KEV dueDates and CVSS not captured; one secondary source cites an Oct 17 deadline for the 10-14 batch — [NeoTeo](https://www.neoteo.com/en/cisa-added-four-exploited-flaws-to-the-kev-catalog)
- CISA BOD 26-04 appears in search results (applies to federal civilian agencies; others encouraged to prioritise KEV); contents not fetched. — [CISA bulletin list](https://content.govdelivery.com/accounts/USDHSCISA/bulletins/4298cb9)

### Inferences
- Old CVEs (2015-2023) added on 10-08 signal opportunistic exploitation of unpatched legacy components (Struts, Strapi, BIND).

### Gaps
- CVE-number scheme in the 2026 data contains very high sequence numbers (e.g. CVE-2026-110936); I could not independently confirm via NVD. Treat IDs as as-reported by CISA's page.
- No CISA advisory text on Python-specific items; KEV entry 2026-09-02 for Starlette is from secondary sources only.

## (d) Breaches and supply-chain incidents

### Takeaway
Two Python-relevant incidents dominate: (1) LiteLLM 1.107.0 malicious PyPI/Docker release (reported 2026-10-21) via stolen GitHub CLI OAuth tokens and a bypassed approval; (2) the GhostAction GitHub Actions campaign (Oct 7-9) that used stolen PATs to push credential-stealing workflows. Both are token-hygiene failures.

### Cited Findings
- LiteLLM 1.107.0 compromise, article dated 2026-10-21. Attackers stole GitHub CLI OAuth tokens from at least three engineer accounts; one account triggered the project-releaser Actions workflow, a second approved it (defeating four-eyes review). Tampered PyPI wheels and Docker images contained a rogue `cook.pth` that executes at interpreter startup, harvests credentials (cloud, AI provider, SSH/TLS, browser), POSTs a GZIP TAR to an attacker domain, and polls a GitHub dead-drop repo hourly for code to execute. Packages quarantined on PyPI; tokens revoked. Remediation: assume compromise of any host that installed 1.107.0, rotate reachable credentials, hunt for cook.pth, egress allowlisting, pin deps by digest, enforce multi-party release approval. Source is a vendor blog (Aviatrix); how the tokens were stolen is speculation there. Article also cites an earlier March 2026 TeamPCP LiteLLM compromise (no details). — [Aviatrix](https://aviatrix.ai/threat-research-center/litellm-compromised-supply-chain-attack-credential-stealer-backdoor/)
- GhostAction campaign. 2026-10-07/08: maintainer accounts (Takashi Kitao, Henry Wu) used to push "Security Audit" workflows (security-audit.yml / github_actions_security.yml) directly to default branches without PRs; first count 345 repos (27 + 318 in 16 minutes). GitHub began blocking the workflow 2026-10-09. GitGuardian update: about 1,900 accounts, more than 30,000 repos targeted, 3,174 secrets targeted (targeted, not confirmed stolen). Separate GitGuardian figure for Aug 31-Sep 30: 772 repos, 2,577 secrets targeted. Payload scans 13 credential patterns, scans full git history (`git log --all`), exfiltrates over plain HTTP to 193.32.204[.]199. Likely entry: leaked PATs from infostealer logs (inference, unconfirmed). Confirmed exfiltration from uber/athenadriver. Remediation: search for the workflow names/IP, rotate every credential ever committed, revoke the PAT, require approval for workflow runs, protect .github/workflows with branch protection, runner egress allowlists. — [DIESEC](https://diesec.com/2026/10/ghostaction-github-actions-attack-steals-secrets/); [SC World](https://www.scworld.com/brief/ghostaction-campaign-escalates-targeting-over-30000-github-repositories); [StepSecurity](https://www.stepsecurity.io/blog/ghostaction-returns). Counts conflict across sources (346/345, 790, 772, 30,000+) because they measure different things.
- OVHcloud CLI supply-chain attack, reported 2026-10-19: attackers replaced GitHub release assets for several versions with malicious binaries to steal developer secrets. Only a DEV Community snippet seen; details unverified. — [DEV Community](https://dev.to/anoymask/ovhcloud-cli-supply-chain-attack-release-assets-replaced-to-steal-developer-secrets-2d2i)
- Background (June 2026): Klue (competitive-intel SaaS) breach, detected 2026-06-12; attacker used a compromised legacy credential tied to an integration service to obtain OAuth tokens for third-party platforms including Salesforce; about 12 Salesforce environments reportedly hit, LastPass among them (contact/support data, not vaults). — [SOCRadar](https://socradar.io/blog/klue-breach-what-to-know/); [CybelAngel](https://cybelangel.com/blog/lastpass-forgotten-credential/)
- Background: Zscaler token-based breach via third-party attack (support data exposed; date not captured). — [National CIO Review](https://nationalcioreview.com/articles-insights/information-security/cloud-security-firm-zscaler-hit-by-token-based-data-breach/)

### Inferences
- Common root causes: long-lived PATs/OAuth tokens without rotation or scoping; release workflows where one compromised identity chain can both trigger and approve; secrets committed once and left in git history; unrestricted CI egress.
- Python-specific lesson: `.pth` files execute at interpreter start, so pip-installed malware needs no import; pin by hash (`pip install --require-hashes`) and install new releases after a cooldown.

### Gaps
- No in-window breach found for identity providers (Okta/Entra), major CI providers, or cloud tenants beyond the above; searches were limited (two general queries). Misconfigured-bucket and SSRF-rooted breaches in the window not found.
- "What did CISA/vendors urge": only KEV/BOD 26-04 generic guidance and per-vendor upgrade advice found; no CISA alert specific to Python or the GhostAction/LiteLLM incidents was located.
- LiteLLM and OVHcloud details rely on single vendor-blog/community sources; no PyPI or BerriAI primary advisory was fetched.
