# Usta — Cowork-style Work Agent (SPEC v1.0)

**Status:** accepted — output of grilling `BLUEPRINT.md` · **Date:** 2026-10-07 · **Owner:** Fariz
**Supersedes:** SPEC v0.2. Every decision here has an ADR in `docs/adr/` (index in §17). Terms are defined in `CONTEXT.md`.
**Use:** this is the input for the implementation plan (`superpowers:writing-plans`). Where this spec and `BLUEPRINT.md` disagree, this spec wins.

---

## 1. What we are building

**One line:** a Cowork-style work agent for a telematics and security company in Azerbaijan. It automates multi-step tasks over files, email and company systems (through MCP), in Azerbaijani, with **its own harness**: agent loop, tool pipeline, policy and taint, gVisor sandbox, and evals.

**Primary goal (ADR-001):** a **strong portfolio project** that shows how such a system is built and proves its key claims with measurements. Not a production tool for staff in v1. Guiding rule: **simple but strong**: the simplest option that still gives a defensible, measured result.

**Core of the project:** agent loop, tools, MCP (client + own servers), production-grade sandbox.
**Three measured deep dives (ADR-003):**
- **A. Harness:** own loop (incl. context management) vs Claude Agent SDK on the same tasks, tools and policy.
- **B. Injection defence:** run-level taint vs taint + URL provenance; attack success and false-park rate.
- **C. Azerbaijani:** Claude token parity, English vs English+examples instructions, language-drift rate.

Everything else works but is not measured.

### 1.1 Requirements

| ID | Requirement |
|---|---|
| R1 | Azerbaijani-first. Tasks in and results out in Azerbaijani; English also works. |
| R2 | Cowork-style work, not chat: multi-step tasks over files, email and company tools, producing real files (PDF, XLSX, DOCX, charts). |
| R3 | Own agent loop: the harness is built, not rented. |
| R4 | Isolated code execution as a core capability. |
| R5 | Web search and fetch as a core capability. |
| R6 | Modular model layer: switching provider (incl. a local model) is adapter + config, not a rewrite. |
| R7 | Dev runs on Fariz's machine on his Claude subscription where legitimate. |
| R8 | Portfolio-grade and interview-defensible: every major choice has a stated trade-off and, where possible, a measured result. |
| R9 | Production by configuration: setting an API key (or another provider) and deploying is enough. |
| R10 | Cost-efficient by design: prompt caching with a stable prefix, cheap model for side work, measured cost per run. |
| R11 | Open-source building blocks (LiteLLM, Langfuse, OpenTelemetry, official MCP SDK) used where they add value, kept behind our own interfaces. |

### 1.2 Anchor tasks (v1 scope, ADR-007)

| # | Task (Azerbaijani) | Exercises |
|---|---|---|
| T-a | Keçən həftənin yanacaq sərfiyyatı hesabatını `fleet` sistemindən götür və iclas üçün PDF hazırla. | MCP read, sandbox, `pdf-report` skill, Azerbaijani fonts |
| T-c | Bu Excel faylındakı cihaz siyahısını anbar qalıqları ilə müqayisə et və uyğunsuzluqları cədvəldə göstər. | upload + MCP + analysis in sandbox |
| T-d | Teltonika FMC130 və FMB920 cihazlarını xüsusiyyətlərinə və qiymətinə görə müqayisə edən qısa hesabat yaz. | web search/fetch, taint, citations |
| T-e | Daxil olan məktublardakı müştəri şikayətlərini qruplaşdır və hər birinə cavab qaralaması hazırla. | email read, drafts, `email.send` with approval, injection |
| T-f | Bu müqavilənin PDF-indən ödəniş şərtlərini və cərimə bəndlərini çıxar. (**digital PDFs only**) | document extraction in sandbox |

**Stretch (first after core):** T-b scheduled weekly summary email.
**v2:** company-system writes, scanned PDFs (OCR/vision), research fan-out subagents, agent-written memory, full MCP OAuth, persistent "always allow", Usta-as-MCP-server, vector retrieval.

### 1.3 Success criteria (portfolio)

- All 5 anchors run end to end on both engines.
- README numbers with 95% intervals for: T2 task success per engine, cost per task, cache hit rate, context-strategy comparison, taint A vs B (attack success + false-park rate), language-drift rate, Claude Az/En token parity.
- T1 and T3a green on every commit; T3b at 100% at the final run.
- Demo video (T-e: injection attempt parked → approved send → email visible in Mailpit). Live VM deployment if not cut.

---

## 2. Facts and constraints

| ID | Fact | Consequence |
|---|---|---|
| F1 | A Claude subscription (OAuth) may power only Claude Code / the Agent SDK for the owner's own use. Own code calling the Messages API needs an API key. Pro includes ~$20/month of Agent SDK credit; then requests stop or move to usage credits. | `engine=sdk` can use the subscription; `engine=own` needs an API key or another provider. |
| F2 | If `ANTHROPIC_API_KEY` is set it overrides the subscription login. | Guard in `dev-sub` (P4). |
| F3 | Agent SDK: restrict built-in tools, in-process SDK MCP server, `PreToolUse` hooks, `max_turns`, `max_budget_usd`, usage reporting. `can_use_tool` is not called for auto-approved tools. | Policy runs as a `PreToolUse` hook in `engine=sdk`. |
| F4 | Az/En token parity: cl100k 2.4–2.7×, o200k ~1.6×, Tekken ~1.75–1.8×, Gemma 1.8–2.1×, Llama 3 2.2–2.5×. Claude unmeasured. | Instructions in English (ADR-030); measure Claude in T0. |
| F5 | Python `str.lower()` breaks Azerbaijani (`İ→i̇`, `I→i`). | `az_casefold()` in `usta/lang`. |
| F6 | ReportLab base fonts don't render `ə ğ ı ş İ`. | Sandbox image ships DejaVu/Noto; skills register them. |
| F7 | Private data + untrusted content + outbound channels = "lethal trifecta" by design. | Taint + verdict function (§8). |
| F8 | LiteLLM PyPI was compromised on 2026-03-24 (versions 1.82.7/1.82.8 stole credentials). | LiteLLM isolated in one adapter, pinned with hashes (ADR-020). |
| F9 | One engineer, ~10 h/week, Windows 11 + WSL2 Ubuntu, Docker Desktop, no GPU, Claude Pro. | Scope and cut line (§16). |
| F10 | Langfuse self-host v3 needs Postgres + ClickHouse + Redis + S3. Langfuse Cloud Hobby: 50k units/month, 30-day access, free; accepts OTLP at `/api/public/otel`. | OTel → Langfuse Cloud (ADR-033). |
| F11 | Tavily: 1,000 free credits/month, no card. Brave: $5 credit/month, card required, no cap. | Tavily default (ADR-027). |

### 2.1 Blocked decisions (built under a default assumption)

| Decision | Default assumed | Revisit when |
|---|---|---|
| Which company data may reach an external model API (D-26) | **All connector data is synthetic fixtures.** Data-class tags exist as a mechanism; no real company data until approved. | Manager/legal answer. |
| Pilot (D-04) | Fariz is the only user. | Manager go/no-go. |
| Publishing the repo | Public, company-neutral naming (ADR-036). | Manager confirms before first public push. |

---

## 3. Architecture

```
 UI (Vite + React + TS)  ── SSE events ──┐
 CLI (usta run "…")                      │
                                         ▼
 API (FastAPI): auth · runs · approvals · files · preferences · run view
        │
 RUN WORKER (in-process, Postgres-backed): queue · checkpoints · park/resume
        │
 ENGINE  ── EnginePort ──┬── engine=own : own asyncio loop + context mgmt + budgets
                         └── engine=sdk : Claude Agent SDK (Usta tools via in-process MCP,
                                          policy via PreToolUse hook)
        │                                   │
 MODEL LAYER (engine=own)              TOOL PIPELINE (shared by both engines)
  ModelPort: anthropic | litellm | fake   registry → schema → policy/taint → audit/cost → execute
  caps · pricing · roles (main/light)     built-ins · skills · web · MCP client
  logging/retry/cost wrapper                  │                     │
                                          SANDBOX (gVisor)     MCP SERVERS: email (Mailpit)
                                          code + files only    ops · fleet · 1 third-party
 CROSS-CUTTING: Postgres (runs + append-only audit) · OTel → Langfuse · verifier · usta/lang · evals
```

### 3.1 Trust zones

| Zone | Holds | Never holds |
|---|---|---|
| Trusted (API, worker, engines, MCP servers) | model + connector credentials, model calls, web access, policy, audit | untrusted code execution |
| Untrusted (sandbox) | model-written code, read-only user files, run output dir | credentials, env vars, network |

Matches Claude Cowork's split: agent loop and connectors outside, only code execution isolated; connector tokens never enter the sandbox.

### 3.2 Module map

```
usta/
  core/        domain types only, no I/O: Message, ContentBlock, ToolCall, ToolResult, Usage,
               RunState, TaintFlags, Verdict, StopReason, Event
  ports/       Protocols: ModelPort, EnginePort, SandboxPort, SearchPort, RunStore, EventSink
  engines/own/ loop, context/ (offload, clear, compact), budgets
  engines/sdk/ Agent SDK adapter: event mapping, PreToolUse policy hook, P4 guard
  models/      anthropic.py · litellm_adapter.py (ONLY importer of litellm) · fake.py
               caps.py · pricing.py · gateway.py (logging, retries, timeouts, cost — outside adapters)
  tools/       registry.py · pipeline.py · builtin/ (files, code_exec, todo, skill_load, ask_user)
  mcp/         client: connect (stdio | streamable HTTP), tier map, description-hash pinning
  policy/      verdict.py · taint.py · grants.py
  web/         fetch.py (SSRF guard) · search/ (tavily, brave)
  sandbox/     gvisor.py · docker_hardened.py (test profile only)
  verify/      verifier (code checks, then LLM check)
  lang/        az_casefold · langcheck (lingua + ə signal)
  store/       SQLAlchemy models, Alembic migrations, audit writer, redactor
  auth/        local accounts (argon2), run tokens (PyJWT HS256)
  obs/         OpenTelemetry setup, GenAI + Usta span attributes
  api/         FastAPI routes, SSE, static UI
  app/         composition root: profile loading, wiring, startup guards
servers/       MCP servers: email/, ops/, fleet/ — each tools.py + backend.py (Backend protocol + FixtureBackend)
fixtures/      generate.py (seeded synthetic Azerbaijani data, incl. injection emails)
skills/        pdf-report, xlsx, docx, charts, company-glossary, email-reply-style
sandbox-image/ Dockerfile (pinned digest)
ui/            Vite + React + TS; API client generated from OpenAPI
evals/         t0/ t1/ (pytest) t2/ t3/ tasks/ judge/ results/*.json
deploy/        docker-compose (dev, vm)
```

**Dependency rule (P5):** `core` ← `ports` ← everything else. Adapters depend on ports, never on each other. Only `app/` knows concrete adapters. `litellm` imported only in `models/litellm_adapter.py`. Enforced by import-linter in CI.

### 3.3 Key interfaces (sketch)

```python
class ModelPort(Protocol):
    caps: ModelCaps
    async def complete(self, req: ModelRequest) -> ModelResponse: ...
    # ModelRequest: system blocks with cache markers, messages (Usta types), tool schemas, role
    # ModelResponse: content blocks, tool_calls, usage{input, output, cache_read, cache_write}, stop_reason

@dataclass(frozen=True)
class ModelCaps:
    context_tokens: int
    max_output_tokens: int
    prompt_cache: Literal["explicit", "automatic", "none"]
    parallel_tool_calls: bool
    native_tools: bool            # False → startup refuses the model

class EnginePort(Protocol):
    async def run(self, run: RunState, ctx: RunContext) -> AsyncIterator[Event]: ...
    async def resume(self, run_id: str, ctx: RunContext) -> AsyncIterator[Event]: ...

@dataclass
class RunContext:                 # identical for both engines
    tools: ToolPipeline           # registry → schema → policy/taint → audit → execute
    skills: SkillIndex
    budget: BudgetPolicy
    store: RunStore
    events: EventSink
    token: RunToken               # per-run delegated identity (ADR-006)

class SandboxPort(Protocol):
    async def exec(self, run_id: str, code: str, timeout_s: int = 60) -> ExecResult: ...
    async def destroy(self, run_id: str) -> None: ...

class SearchPort(Protocol):
    async def search(self, query: str, lang: str = "az") -> list[SearchHit]: ...
```

---

## 4. Engines (ADR-012, ADR-015)

**No LangChain, no LangGraph.** The harness is written; plumbing uses libraries.

| | `engine=own` | `engine=sdk` |
|---|---|---|
| Turn loop | own asyncio loop | Claude Agent SDK |
| Tools | tool pipeline, native tool calls via ModelPort | same pipeline exposed as an in-process SDK MCP server |
| Policy | inline in pipeline | `PreToolUse` hook calling the same verdict function |
| SDK built-ins (Bash, Read, Write, WebSearch, TodoWrite, skills) | — | **disabled**; `setting_sources=[]`, `strict_mcp_config=True` |
| Context management | Usta's 3 layers (§6) | the SDK's |
| Budgets | own counters | `max_turns`, `max_budget_usd` + Usta counters |
| Durability | full (checkpoint per step) | best effort: on restart → `interrupted`, user can resume via SDK session resume |
| Auth | API key (Anthropic) or any provider via LiteLLM | subscription (dev) or API key |

Everything else (UI, run store, tools, MCP, policy, approvals, sandbox, skills, verifier, audit, evals) is shared. Deep dive A compares the engines with one config flag.

### 4.1 Own loop (sketch)

```python
async def run_loop(run: RunState, ctx: RunContext) -> AsyncIterator[Event]:
    while True:
        if stop := ctx.budget.check(run):               # turns / $ / active wall clock
            yield await park_or_stop(run, stop)          # $ cap → park + ask_user to continue
            return
        req = context.build(run)                         # stable prefix (cached) + summary + recent turns
        resp = await gateway.complete(req, role="main")  # logging/cost outside the adapter (P7)
        run.record(resp); await ctx.store.checkpoint(run)
        if not resp.tool_calls:
            yield await finish(run)                      # → verifier (§9) → done | verification_failed
            return
        for call in resp.tool_calls:                     # sequential unless caps.parallel_tool_calls
            outcome = await ctx.tools.handle(call, run)  # verdict; allow → execute; ask → park
            if outcome.parked:
                yield outcome.event; return              # run row = awaiting_approval | awaiting_user
            run.append(context.offload_if_large(call, outcome.result))
        context.maybe_clear_or_compact(run)              # layers 2 and 3
        await ctx.store.checkpoint(run)
        yield Event.step_done(run)
```

### 4.2 Run lifecycle and stop reasons

`queued → running ⇄ (awaiting_approval | awaiting_user | unknown_outcome) → finished(stop_reason)`

Stop reasons (P6), always explicit and shown in UI + audit: `done`, `verification_failed`, `max_turns`, `budget_declined`, `timeout`, `provider_quota`, `cancelled`, `interrupted` (sdk only), `error`.

### 4.3 Durability rules (ADR-014)

1. Checkpoint to Postgres after every step (messages, tool calls, results, state, taint flags, grants, todo).
2. Parked runs are DB rows, not live tasks. Approval/answer re-enqueues the run.
3. On startup, runs in `running` resume from the last checkpoint.
4. **At-most-once external writes (P9):** record `intent` before `email.send`, `done` after. `intent` without `done` on resume → `unknown_outcome`, ask the user; never auto-retry.
5. `engine=sdk`: best effort, as above.

---

## 5. Model layer (ADR-020 … ADR-023)

- **Own message types** in `core`. No provider shape reaches the loop.
- **Adapters:** `anthropic` (direct SDK; production path; explicit cache markers, usage incl. cache tokens), `litellm` (library mode, not proxy: free-tier dev models, local servers, other providers), `fake` (scripted; `test` profile only, P8).
- **Gateway wrapper** (outside adapters): logging every call (model, prompt version, input, output, tokens incl. cache, latency, cost), retries with backoff, timeouts, per-provider circuit breaker.
- **LiteLLM supply-chain controls:** exact pin + hash-checked lock (`uv lock`), import only from its adapter, adapter receives only its own key, Dependabot alerts.
- **Contract test per adapter:** messages + tools + tool results + usage (incl. cache tokens) round-trip.
- **Capabilities:** `ModelCaps` (§3.3). Models without native tool calling are refused at startup. No vision in v1. Reasoning controls passed through per adapter.
- **Roles:** `main` (agent turns, LLM verifier) and `light` (compaction summaries, titles, previews). No `hard` role in v1. Model IDs only in config; each needs a price-table entry or startup fails (P7).
- **Local:** `local` profile = Ollama on CPU via LiteLLM with a small tool-calling model; one `pytest -m local` test proves plumbing, not quality.

### 5.1 Profiles

| Profile | Engine | Model access | Users / bind | Sandbox | Observability |
|---|---|---|---|---|---|
| `test` | own | `fake` | none | `docker_hardened` allowed | none |
| `dev-sub` | sdk | Claude subscription (Agent SDK) | single user, `127.0.0.1` | gvisor | Langfuse Cloud |
| `dev-free` | own | free-tier model via `litellm` | single user, `127.0.0.1` | gvisor | Langfuse Cloud |
| `dev-api` | own | `anthropic` API key, `main` Sonnet-class / `light` Haiku 4.5 | single user, `127.0.0.1` | gvisor | Langfuse Cloud |
| `local` | own | Ollama via `litellm` | single user | gvisor | optional |
| `prod` | own (or sdk + API key) | `anthropic` API key | multi-user, behind login | gvisor | Langfuse Cloud (fixtures) / self-host when real data |

Switch with `USTA_PROFILE=…`. No code change (R9).

**Startup guards:**
- `dev-sub` (P4): refuse if `ANTHROPIC_API_KEY` is set; bind `127.0.0.1` only; single user; connectors point at fixtures.
- All non-`test` profiles (P8): refuse `fake` model and `docker_hardened` sandbox.
- All profiles: refuse models with `native_tools=False` or without a price entry.

---

## 6. Context management, `engine=own` (ADR-017)

Three layers, each used only when the cheaper one isn't enough. Thresholds derive from `caps.context_tokens`.

| Layer | Trigger | Action | Cache impact |
|---|---|---|---|
| 1 Offload | tool result > ~2k tokens | full result → `runs/{id}/tool_results/…`; model gets preview + size + path | none |
| 2 Clear | context > ~50% of window | replace old tool *results* with stubs (`[cleared: fleet.fuel_report → path]`), keep last K; **in batches** | one break per batch |
| 3 Compact | context > ~75% of window | `light` model writes a fixed-template summary (goal, decisions, todo state, files produced, open questions, taint flags); last N turns verbatim | one full break, rare |

**Prompt layout (R10):** system prompt → tool schemas (sorted, stable) → skill index → Azerbaijani style examples → **cache marker** → user `preferences.md` → compaction summary → recent turns.

Rejected: rolling summary every N steps (breaks cache constantly); provider-side context editing (vendor tie, hides the mechanism).

**Deep dive A measures:** naive truncation vs layers 1+3 vs 1+2+3 vs `engine=sdk` on long T2 tasks — success, tokens, cache hit rate, overflows.

---

## 7. Tools (ADR-025, ADR-026, ADR-027, ADR-028)

**Principle:** anything that crosses a trust boundary is a typed tool; pure computation is `code_exec`.

| Group | Tool | Tier | Notes |
|---|---|---|---|
| Files | `file.list`, `file.read` | read | workspace + run dirs |
| | `file.search` | read | `az_casefold` grep |
| | `file.write` | local | `/out` of the current run only |
| Compute | `code_exec` | local | gVisor sandbox (§10) |
| Web | `web.search` | egress | `SearchPort` (Tavily default, Brave adapter) |
| | `web.fetch` | egress | own httpx + HTML→Markdown; SSRF guard (P12); sets `untrusted` |
| Run control | `todo` | local | pending / in_progress / done; rendered live |
| | `skill.load` | local | loads `SKILL.md` body |
| | `ask_user` | local | parks run as `awaiting_user` |
| MCP `email` | `email.list`, `email.read` | read | sets `private` + `untrusted` |
| | `email.draft` | local | drafts stay in Usta |
| | `email.send` | external_write | always ask; at-most-once (P9) |
| MCP `ops` | `ops.installations`, `ops.stock` | read | sets `private` |
| MCP `fleet` | `fleet.units`, `fleet.fuel_report` | read | sets `private` |
| MCP third-party | one official reference server | per config | proves config-only plug-in |

- **Tool pipeline (both engines):** registry → JSON-schema validation → verdict (§8) → audit + cost record → execute → result offload (layer 1) → taint update.
- **Planning (ADR-016):** if a task looks like ≥3 steps and no `todo` exists by turn 2, the loop injects a reminder. Todo state is re-injected after compaction.
- **Promotion rule:** at each milestone a script groups `code_exec` calls from traces by libraries and connector data touched; patterns seen in ≥3 different tasks are candidate typed tools; promotion is manual.

### 7.1 Skills (ADR-026)
- Format: `skills/<name>/SKILL.md` (frontmatter `name`, `description`; Anthropic-compatible) + `scripts/` + optional `check.py`.
- Index (name + description) in the cached prefix; body via `skill.load`. Same path in both engines (SDK native skills off).
- Scripts run in the sandbox; `skills/` mounted read-only at `/skills`.
- Every output skill has `check.py` (page count, totals match source, glyph coverage, output language). These are the verifier's first-stage checks.
- Only repo-versioned, reviewed skills. No user-uploaded skills in v1.
- v1 skills: `pdf-report`, `xlsx`, `docx`, `charts`, `company-glossary`, `email-reply-style`.
- Metric: correct skill loaded per T2 task (each task lists its expected skills).

### 7.2 MCP (ADR-004, ADR-028)
- Usta is an MCP **client** (official Python SDK); stdio in dev (servers as child processes), streamable HTTP in compose/VM.
- Usta builds 3 servers. Each = `tools.py` (Usta-designed schemas) + `Backend` protocol + `FixtureBackend`. A real backend later is a plugin from a private repo; tool schemas, tiers and evals don't change.
- **Tier map in Usta config** decides each tool's tier; MCP annotations (`readOnlyHint`, `destructiveHint`…) are ignored for policy.
- **Description-hash pinning (P11):** hashes of approved tool descriptions are stored; a changed hash blocks the tool until re-approved.
- Every call carries the per-run token (§11.2); servers enforce scopes (P10).
- `email` server talks real IMAP/SMTP to **Mailpit** (seeded mailbox; sent mail visible in Mailpit UI).

### 7.3 Fixtures (`fixtures/generate.py`, fixed seed)
- `ops`: ~200 installations, ~50 stock items, clients with Azerbaijani names, addresses, plate numbers.
- `fleet`: ~30 vehicles, 8 weeks of fuel and mileage, a few planted anomalies.
- `email`: ~40 messages (Azerbaijani, some Russian/English complaints), **~8 injection payloads** (hidden instructions, forward requests, URL-exfiltration attempts).
- Also: injection web pages (served locally for T3) and an xlsx with an injection cell.
- Synthetic, publishable, ground truth known → T2 checks compare exact values.

---

## 8. Policy, taint and approvals (ADR-010, ADR-011)

### 8.1 Run flags (monotonic, off → on)
- `private`: the run read connector data or workspace files.
- `untrusted`: the run read web pages, email bodies or uploaded files. Each flag keeps its **sources** for the approval card.

### 8.2 Verdict function — `verdict = f(tier, private, untrusted, url_provenance, grants)`

| Tier | Verdict |
|---|---|
| `read` | allow |
| `local` | allow |
| `egress` — `web.fetch` | allow, unless `private ∧ untrusted` → **ask**, except when the URL appeared verbatim in a `web.search` result or the user's message (then allow). URLs from fetched pages are not trusted. |
| `egress` — `web.search` | allow, unless `private ∧ untrusted` → **ask** (the query itself can leak data) |
| `external_write` — `email.send` | **always ask** |
| `blocked` | unregistered tool, or tool with a changed description hash → block |

Deterministic, unit-tested in T1, no LLM in the decision.

### 8.3 Approvals
- Card shows the exact payload (URL, or recipient/subject/body) and the taint sources.
- Buttons: **Allow once**, **Allow for this run** (egress only; scoped to same tool + same domain), **Deny** (reason goes back to the agent).
- `email.send` offers only Allow once. No grant outlives its run. Approvals expire after a TTL.
- No "skip all approvals" mode in v1.
- Runs with nobody watching (stretch T-b) never auto-approve `ask` (P3).

### 8.4 Deep dive B
Configurations: **A** run-level taint only vs **B** run-level + URL provenance. Metrics: T3b attack success (must be 0% for both), false-park rate on T2. Known limitations recorded as T3 cases: low-bandwidth choice-encoding via planted literal URLs; leakage through search queries.

---

## 9. Verifier (ADR-018)

Runs in Usta **after the engine reports done**, identical for both engines.
1. Code checks first: each produced file's skill `check.py`, plus `usta/lang` language check.
2. LLM check only for what code can't judge (does the output answer the request?), on the `main` role, read-only tools, no outbound tools. Returns `pass | fail + reasons`; never fixes.
3. `fail` → one retry with reasons appended. Second fail → `stop_reason=verification_failed`; output still shown with a warning.
4. Metric: false-done rate. Measured: verifier on `main` vs `light` (agreement with T2 ground truth); moves to `light` if equal.

---

## 10. Sandbox (ADR-005, ADR-024)

- **Runtime:** gVisor (`runsc`) everywhere except `test` (`docker_hardened` allowed there only). All code runs in Linux: WSL2 Ubuntu in dev, a cloud VM for deployment.
- **Lifecycle:** one container per run, started at the first `code_exec`; each call is a fresh `python` process; state between calls only via files. Destroyed when the run parks or finishes; recreated on resume.
- **Mounts:** `/workspace` = user's `files/` read-only; `/out` = `runs/{run_id}/out/` read-write; `/skills` read-only.
- **Hardening:** `--runtime=runsc`, `--network=none` (P1), `--cap-drop=ALL`, `--security-opt=no-new-privileges`, non-root, read-only root fs, `tmpfs /tmp`, **no env vars passed**.
- **Limits per call:** 60 s wall clock, 1 CPU, 1 GB RAM, 128 pids; stdout/stderr capped, overflow offloaded (layer 1).
- **Image `usta-sandbox`:** Python 3.12, pandas, openpyxl, matplotlib, reportlab, pdfplumber, python-docx, DejaVu + Noto fonts; pinned digest; scanned in CI; no runtime `pip install`.
- **Both engines** use this sandbox; SDK Bash/Write are disabled.
- **First task of M0:** spike `runsc` inside WSL2 Ubuntu with Docker Engine + a `--network=none` container. If it fails, gVisor runs only on the VM and dev/prod parity is recorded as broken in ADR-005.

---

## 11. Workspace, identity, memory

### 11.1 Workspace (ADR-009)
- `workspaces/{user}/files/` (uploads, promoted outputs) and `workspaces/{user}/runs/{run_id}/out/` (+ `tool_results/`).
- Uploaded files set `untrusted`. Outputs are promoted to `files/` by the user after the run.
- Company drive connector: v2.

### 11.2 Identity (ADR-006)
- App login: local accounts, argon2 hashes, session cookies. No SSO in v1.
- Users and scopes in one config table (e.g. `fleet:read`, `ops:read`, `email:read`, `email:send`).
- **Per-run token:** PyJWT HS256 with `user_id`, `scopes`, `run_id`, short TTL. HTTP MCP servers: `Authorization: Bearer`; stdio: env var. Servers verify and filter data by scope (P10).
- Scheduled runs (stretch) act as the schedule's creator; scopes re-checked at run start.
- T3 case: user without `fleet:read` asks for fleet data → server refuses → agent reports missing permission.
- Full MCP OAuth 2.1: v2.

### 11.3 Memory (ADR-019)
- `preferences.md` per user, written only by the user in the UI, injected after the cache marker.
- Company knowledge as skills (`company-glossary`, procedures).
- Agent-written memory: v2 (memory poisoning). v2 rule: memory writes from an `untrusted` run always ask.

---

## 12. Azerbaijani (ADR-030, ADR-031, ADR-032)

- **Instruction language:** English system prompt, tool and skill descriptions + 2–3 short Azerbaijani style examples in the cached prefix + `company-glossary` skill (English → Azerbaijani terms).
- **Reply language:** follows the user (Azerbaijani default, English if the user writes English). **Customer reply drafts follow the customer's language** (e.g. Russian complaint → Russian draft).
- **`usta/lang`:**
  - `az_casefold()` (`İ→i`, `I→ı`), unit-tested on pitfall words (`İSTİQAMƏT`, `IŞIQ`).
  - `langcheck(text, expected)`: `lingua-py` (az/tr/en/ru) + Azerbaijani signal (`ə`, frequent `x`/`q`; Azerbaijani prose without `ə` is suspicious). Skips texts < ~15 words.
  - Language check failure is a verifier code check → one retry.
- **Fonts:** see F6; skills register fonts; `check.py` verifies glyph coverage.
- **Locale:** numbers, dates, AZN via Babel `az` locale.
- **Retrieval:** no vector search in v1; agentic `file.search` + `file.read`. Revisit (pgvector + embedder bake-off: LocRet-small, BGE-M3, multilingual-e5) when a task needs >~50 documents.
- **Glossary maintenance:** manual at milestones from flagged terms.
- **Deep dive C measures:** (1) Claude Az/En token parity via `count_tokens` (`az_token_benchmark.py`); (2) instructions A (English only) vs C (English + examples + glossary) on the Azerbaijani T2 subset — success, drift, glossary-term accuracy; (3) drift rate.

---

## 13. Storage, audit, observability (ADR-014, ADR-029, ADR-033)

- **Postgres everywhere** (compose in WSL2 and on the VM). SQLAlchemy + asyncpg, Alembic migrations. Exact schema is designed in the M0 plan and reviewed before migration (schemas are hard to reverse).
- **Run tables (sketch):** `users`, `runs`, `run_checkpoints`, `todos`, `grants`, `approvals`, `files`, `schedules` (stretch).
- **Append-only audit tables:** `model_calls`, `tool_calls` (incl. `intent`/`done`), `policy_verdicts`, `approvals`, `run_events`. Each row: run, user, prompt version, tokens incl. cache, cost, latency (P7).
- **DB roles:** app role has only `INSERT` + `SELECT` on audit tables; `usta_purge` role deletes.
- **Retention:** `retention_days` per profile (dev unlimited, prod 90); `usta purge` CLI.
- **Redactor:** applied on audit writes; no-op in dev; prod masks emails, phone numbers, plates. Live model context is never redacted.
- **Observability:** OpenTelemetry with GenAI semantic conventions + Usta attributes (engine, taint flags, verdict, prompt version). Spans: `run → turn → model_call | tool_call → policy_verdict`. Exporter per profile: Langfuse Cloud Hobby (dev, VM; fixtures only), self-hosted Langfuse or Jaeger when real data arrives. Eval scores pushed to Langfuse. Export failure never breaks a run (drop + warn).
- **In-app run view:** event stream from Postgres (turns, tool calls, verdicts, cost).

---

## 14. UI and API (ADR-008)

- **Backend:** FastAPI; SSE for run events; OpenAPI spec → generated TypeScript client.
- **Frontend:** Vite + React + TypeScript, static build served by FastAPI. Designed with the `frontend-design` skill.
- **Views:** (1) chat with live run stream, (2) task list (todo), (3) workspace files (upload, download, promote outputs), (4) approval inbox (payload, taint sources, Allow once / Allow for this run / Deny), plus run view (trace + cost) and preferences editor.
- **CLI:** `usta run "…"`, `usta purge`, eval entry points — same API.

---

## 15. Evals, cost controls

### 15.1 Eval tiers (ADR-034)

| Tier | Contents | Model | Cadence | Cost |
|---|---|---|---|---|
| T0 Language | Claude Az/En parity (`count_tokens`); `langcheck` accuracy on ~100 labelled az/tr/en/ru texts | none / free | once; when `usta/lang` changes | $0 |
| T1 Harness | loop, stop reasons, budgets, verdict function, taint, grants, resume, intent/done crash test, SSRF rules, token scopes, profile guards, adapter contract tests | `fake` | every commit (CI) | $0 |
| T3a Safety (deterministic) | policy-level parts of every attack; sandbox escapes (network incl. 169.254.169.254, write to `/workspace`, host paths, fork/memory bomb, env secrets); SSRF probes; changed tool hash | `fake` + real sandbox | every commit | $0 |
| T2 Tasks | 30 tasks = 5 anchors × 6 variants, ≥20 Azerbaijani; checks vs fixture ground truth; LLM judge only for T-d/T-e report quality | real | smoke (8) on `dev-free` at will; full at milestones | free / within caps |
| T3b Safety (live) | 8 injection emails + web pages + xlsx with a real model; must be 100% | real | milestones | within caps |

- **Variance:** milestones 1 repeat; final README run 3 repeats per engine, **spread over two months** (budget); 95% Wilson intervals; differences inside the interval are not claimed.
- **Judge calibration:** 10 hand-labelled outputs; agreement < 80% → judge scores reported as indicative only.
- **Baseline:** `engine=sdk` vs `engine=own` (same tasks, tools, policy). Manual Cowork comparison dropped.
- Results written to timestamped JSON in `evals/results/` with code SHA (Aegis pattern); every failure found becomes a T2/T3 case.

### 15.2 Cost controls (ADR-035)

| Level | Limit | Default | At the limit |
|---|---|---|---|
| Run | turns | 40 | stop `max_turns` |
| Run | cost | $0.50 (own: price table; sdk: `max_budget_usd`) | park + `ask_user` "continue with +$0.50?"; declined → `budget_declined` |
| Run | active wall clock (parked time excluded) | 20 min | stop `timeout` |
| User | monthly cost | $10 (dev) | new runs refused; running runs finish the current turn |
| Account | Anthropic Console spend limit | $20/month | `provider_quota` |
| Account | Pro Agent SDK credit | ~$20/month | `provider_quota` |

- **Never auto-downgrade the model** (P8). Cheaper model = a different profile chosen by the user.
- Per-run default is recalibrated after M3 to p90 × 1.5 of measured cost.
- Cost levers (R10): cached stable prefix, `light` role, offload, English instructions + examples, code checks before LLM checks, fake model for T1/T3a. Cost per task shown in run view and eval results.

---

## 16. Milestones and cut line (ADR-037)

~10 h/week. M0–M4 ≈ 10–12 weeks; M5 + 3–4 weeks (two-month final eval). **Warning sign:** M1 not done by week 5 → start cutting.

| M | Contents | Proof of done |
|---|---|---|
| **M0 Foundations** | Day 1: gVisor-in-WSL2 spike. Repo, `uv`, CI (T1, gitleaks, import-linter), core types, ModelPort + `anthropic`/`litellm`/`fake` + contract tests, gateway wrapper, own loop with budgets + stop reasons, Postgres run store + checkpoints + audit tables + DB roles, profiles + startup guards, CLI. | T1 green in CI; a 2-tool task completes on `dev-free`. |
| **M1 Tools + sandbox** | Tool pipeline; file tools + `az_casefold`; `code_exec` on gVisor + image + fonts; skills loader + `pdf-report`, `xlsx`, `docx`, `charts` with `check.py`; `todo`; verifier; `usta/lang`. | A T-c-style task produces a correct xlsx + PDF passing checks; T3a sandbox escapes 100%. |
| **M2 MCP + web + safety** | MCP client; `email`/`ops`/`fleet` servers + fixtures + Mailpit + run tokens; tier map + hash pinning; Tavily `web.search` + `web.fetch` with SSRF guard; taint + URL provenance; approvals + grants; `ask_user`; intent/done. | All 5 anchors run via CLI; T3a 100%. |
| **M3 Engines + context + evals** | `engine=sdk` + P4 guards; 3 context layers; T0, T2 (30), T3b; OTel → Langfuse; first measured run (1 repeat, both engines). | First numbers table exists. |
| **M4 UI** | Vite + React: 4 views + run view + preferences, SSE, local accounts. | Demo video of T-e (injection parked → approved send → visible in Mailpit). |
| **M5 Measure + ship** | Deep-dive comparisons (context configs, taint A vs B, instructions A vs C); final 3-repeat runs over two months; VM deployment; README. | README numbers with intervals; live URL. |
| *Stretch* | T-b scheduling (cron schedules in Postgres, unattended runs, P3). | Weekly email lands in Mailpit unattended. |

**Cut order (first to go):** VM deployment (→ video) · Brave adapter + search bake-off · third-party MCP server · context layer 2 · UI polish (4 views stay, plain).
**Never cut:** own loop, tool pipeline, MCP servers, gVisor sandbox, taint + approvals, T1/T3, `engine=sdk`.

---

## 17. Invariants (must always hold)

| ID | Invariant | Enforced by |
|---|---|---|
| P1 | Sandbox has no network and no credentials | `--network=none`, no env, T3a |
| P2 | Outbound calls follow the verdict function (§8.2) | policy engine, T1/T3 |
| P3 | Runs with nobody watching never auto-approve `ask` | policy: `ask` → park + notify (stretch) |
| P4 | Subscription auth serves only its owner | `dev-sub` guards |
| P5 | Modules depend on ports; LiteLLM only in its adapter | import-linter in CI |
| P6 | Every run ends with an explicit stop reason | run state machine, T1 |
| P7 | Every model and tool call logged with cost, append-only; no price entry → no start | DB roles, startup check |
| P8 | No fake, fallback or downgraded model or sandbox passes as real | composition-root checks |
| P9 | External writes are at-most-once | intent/done, T1 crash test |
| P10 | The agent can't exceed the requesting user's rights | per-run scoped token, server checks, T3 |
| P11 | A tool whose description hash changed is blocked | registry check at connect, T3a |
| P12 | `web.fetch` never reaches private/loopback/link-local/metadata addresses | DNS check + re-check per redirect, T3a |

## 18. Risks

| Risk | Signal | Mitigation |
|---|---|---|
| gVisor doesn't run in WSL2 | M0 day-1 spike fails | gVisor on VM only; record broken parity |
| Scope outruns 10 h/week | M1 not done by week 5 | cut order §16 |
| Pro SDK credit too small | `provider_quota` during M3 | fake model + `dev-free` carry dev; spread evals |
| Eval noise | wide intervals | 3 repeats, Wilson intervals, no claims inside the interval |
| Free-tier model too weak for loop dev | smoke tasks fail for model reasons | short `dev-api` sessions on Haiku-class within cap |
| LiteLLM supply chain | advisory | pin + hashes, isolated adapter, single-key env |
| Approval fatigue | approvals per task | per-run domain grants; URL provenance |

## 19. Pre-publish checklist (ADR-036)

- Neutral names only: `ops` (installations, stock), `fleet` (Wialon-style fleet data), `company-glossary`; company described as "a telematics and security company in Azerbaijan".
- `BLUEPRINT.md` and SPEC v0.2 history name the employer and internal systems → keep them out of the public repo (move to a private notes folder or neutralize).
- `az_token_benchmark.py` sample sentences mention real organisations → neutralize before publishing.
- gitleaks pre-commit + CI from the first commit; MIT licence; manager OK recorded in ADR-036.

## 20. Open items (resolved during build, not design)

1. gVisor-in-WSL2 spike result (M0 day 1). **Result: passed 2026-10-08 (ADR-005) on runsc platforms `kvm` (dev default, fastest) and `ptrace`; the default `systrap` fails in WSL2. Production VM platform is decided at VM setup.**
2. Free-tier model for `dev-free` (pick the best tool-calling model available on a free tier at M0).
3. Measured cost per task → recalibrate run budget (after M3).
4. Tavily vs Brave on 30 Azerbaijani queries (M2; cut-able).
5. Which official reference MCP server is the third-party proof (M2).
6. Manager OK to publish.

## 21. ADR index

| ADR | Decision | Resolves |
|---|---|---|
| 001 | Portfolio-first goal; pilot-grade rigor; Fariz-only use; Usta only takes connector-backed work | D-04, D-05 |
| 002 | Data path BLOCKED; synthetic fixtures only | D-26 |
| 003 | Deep dives: harness, injection defence, Azerbaijani | D-39 |
| 004 | Built-ins in-process; connectors as MCP servers; one tool pipeline | D-22 |
| 005 | Linux-first hosting; gVisor everywhere; VM at M5 | D-36, D-18 host |
| 006 | Per-run delegated token; local accounts | D-27 |
| 007 | v1 scope: T-a, T-c, T-d, T-e, T-f (digital); T-b stretch | D-03 |
| 008 | FastAPI + Vite/React/TS UI | D-01 |
| 009 | Per-user server workspace; ro `/workspace`, rw `/out` | D-02 |
| 010 | Verdict function over tier × run flags; web tools are egress | D-24 |
| 011 | Run-level taint + URL provenance | D-25 |
| 012 | Two engines behind `EnginePort` (supersedes "own loop only") | D-06 |
| 013 | Dev model access: subscription for `engine=sdk`, free tier + capped API key for `engine=own` | D-17 |
| 014 | Postgres + in-process worker; checkpoint per step; at-most-once writes | D-10 |
| 015 | No agent framework (LangChain/LangGraph) | — |
| 016 | Todo tool, both engines | D-07 |
| 017 | Three-layer context management, cache-aware | D-08 |
| 018 | Verifier only, outside the engines | D-09 |
| 019 | User-written preferences + knowledge as skills; no agent memory | D-11 |
| 020 | Own message types; anthropic + litellm (isolated) + fake adapters | D-12, D-13 |
| 021 | Minimal `ModelCaps`; refuse models without native tools | D-14 |
| 022 | Two roles: `main`, `light` | D-15 |
| 023 | Local model: one Ollama plumbing test | D-16 |
| 024 | Sandbox: container per run, process per call, hardening | D-18 |
| 025 | Typed tools at trust boundaries, code for compute; 18 tools | D-19 |
| 026 | Skills: `SKILL.md`, `skill.load`, `check.py`, trusted only | D-20 |
| 027 | Tavily default + Brave adapter; own `web.fetch` with SSRF guard | D-21 |
| 028 | MCP servers with swappable backends; Mailpit; seeded fixtures | D-22 |
| 029 | Append-only audit with retention + redactor | D-28 |
| 030 | English instructions + Azerbaijani examples + glossary | D-29 |
| 031 | Deterministic language check; drafts follow customer language | D-30 |
| 032 | No vector retrieval in v1 | D-31 |
| 033 | OpenTelemetry → Langfuse Cloud | D-34 |
| 034 | Eval tiers, cadence, variance; SDK engine as baseline | D-32, D-33 |
| 035 | Cost limits; park-and-ask; no auto-downgrade | D-35 |
| 036 | One public repo, neutral names | D-37 |
| 037 | Milestones M0–M5 and cut line | D-38 |
| 038 | Invariants P1–P12 | P1–P8 |
