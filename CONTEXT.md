# Usta — Glossary

Shared vocabulary for code, docs and conversations. See `SPEC.md` for design, `docs/adr/` for decisions.

| Term | Meaning |
|---|---|
| **Run** | One execution of a user task, from `queued` to a stop reason. Persisted in Postgres. |
| **Engine** | What drives the turn loop: `own` (Usta's asyncio loop) or `sdk` (Claude Agent SDK). Everything else is shared. |
| **Profile** | Named config (`test`, `dev-sub`, `dev-free`, `dev-api`, `local`, `prod`) selecting engine, model adapter, sandbox, users, exporters. |
| **Turn** | One model call plus the tool calls it requests. |
| **Checkpoint** | Run state saved to Postgres after every turn; the resume point. |
| **Stop reason** | Explicit end state: `done`, `verification_failed`, `max_turns`, `budget_declined`, `timeout`, `provider_quota`, `cancelled`, `interrupted`, `error`. |
| **Park** | A run waiting for a human (`awaiting_approval`, `awaiting_user`, `unknown_outcome`). A DB row, not a live task. |
| **Tool pipeline** | registry → schema validation → verdict → audit + cost → execute → offload → taint update. Same for both engines. |
| **Tier** | A tool's risk class set in Usta config: `read`, `local`, `egress`, `external_write`, `blocked`. |
| **Verdict** | `allow`, `ask` or `block`, from the deterministic verdict function. |
| **private / untrusted** | Monotonic run flags: read company/workspace data; read web, email bodies or uploads. Both on = lethal-trifecta state. |
| **Taint sources** | The tool results that set a flag; shown on approval cards. |
| **URL provenance** | Whether a fetch URL appeared verbatim in a search result or the user's message (trusted) or not. |
| **Grant** | "Allow for this run" approval scoped to the same tool + domain; egress only; dies with the run. |
| **Intent / done** | Audit records before and after an external write; an intent without done = unknown outcome. |
| **Run token** | Short-lived JWT (`user_id`, `scopes`, `run_id`) passed to MCP servers; servers enforce scopes. |
| **Backend** | The data source behind an MCP server's tools: `FixtureBackend` now, real backends as private plugins. |
| **Description hash** | Pinned hash of an MCP tool's description; a change blocks the tool. |
| **Skill** | `skills/<name>/SKILL.md` + scripts + optional `check.py`; index in prompt, body via `skill.load`. |
| **Verifier** | Post-run check outside the engines: code checks, then an LLM check; reports, never fixes. |
| **Offload / clear / compact** | Context layers 1–3: big results to files; old results to stubs; structured summary by the `light` model. |
| **Role** | `main` or `light`; mapped to concrete models per profile. |
| **ModelCaps** | Capability descriptor per model: window, max output, cache kind, parallel tools, native tools. |
| **Workspace** | `workspaces/{user}/files/` (ro in sandbox) and `runs/{run_id}/out/` (rw). |
| **Sandbox** | gVisor container per run; process per `code_exec`; no network, no env. |
| **T0–T3** | Eval tiers: language, harness (fake model), tasks, safety (T3a deterministic, T3b live). |
| **Anchor tasks** | T-a, T-c, T-d, T-e, T-f (v1); T-b (stretch). |
| **az_casefold** | Azerbaijani-correct case folding (`İ→i`, `I→ı`). |
| **langcheck** | Deterministic output-language check (lingua + `ə` signal). |
