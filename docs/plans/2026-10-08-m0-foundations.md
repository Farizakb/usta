# M0 Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Usta's M0 foundations (SPEC §16): gVisor spike, repo + CI, core types, ModelPort with `anthropic` / `litellm` / `fake` adapters and contract tests, gateway, own loop with budgets and stop reasons, Postgres run store with checkpoints, audit tables and DB roles, profiles with startup guards, and a CLI. Done when T1 is green in CI and a 2-tool task completes on `dev-free`.

**Architecture:** Hexagonal. `usta.core` holds pure Pydantic domain types and `usta.ports` holds Protocols. Adapters, the engine, tools, store and worker depend only on those two, and only `usta.app` (the composition root) knows concrete classes. import-linter enforces this in CI. The own asyncio loop drives turns through a `Gateway` (logging, retries, timeouts, circuit breaker, cost) and a `ToolPipeline` (registry, schema, audit, execute). It checkpoints `RunState` to Postgres after every step.

**Tech Stack:** Python 3.12, uv, Pydantic v2, pydantic-settings, SQLAlchemy 2 (Core, asyncio) + asyncpg, Alembic, Postgres 17, jsonschema, anthropic 1.x (httpx2), LiteLLM (exact pin), pytest + pytest-asyncio, ruff, import-linter, GitHub Actions, gitleaks.

**Spec:** `SPEC.md` (v1.0). The M0 row is in §16. The ADRs are in `docs/adr/` and the terms are in `CONTEXT.md`. Executors read SPEC.md alongside this plan.

**Where to run:** every command runs in **WSL2 Ubuntu**, in a clone at `~/code/usta` (Task 0), using bash. Nothing runs on the Windows side.

## Global Constraints

- Python `>=3.12,<3.13`; dependency management with `uv`; lock file committed; CI uses `uv sync --locked`.
- "All code runs in Linux: WSL2 Ubuntu in dev, a cloud VM for deployment." (SPEC §10)
- "No LangChain, no LangGraph." (ADR-015)
- P5: "`core` ← `ports` ← everything else. Adapters depend on ports, never on each other. Only `app/` knows concrete adapters. `litellm` imported only in `models/litellm_adapter.py`. Enforced by import-linter in CI."
- LiteLLM: "exact pin + hash-checked lock (`uv lock`), import only from its adapter, adapter receives only its own key". Never versions 1.82.7 / 1.82.8 (F8).
- "Own message types in `core`. No provider shape reaches the loop." (SPEC §5)
- P7: "Every model and tool call logged with cost, append-only; no price entry → no start."
- P8: "No fake, fallback or downgraded model or sandbox passes as real." "Never auto-downgrade the model."
- P6: every run ends with one of `done`, `verification_failed`, `max_turns`, `budget_declined`, `timeout`, `provider_quota`, `cancelled`, `interrupted`, `error`.
- Run limits: 40 turns → `max_turns`; $0.50 → "park + `ask_user` 'continue with +$0.50?'; declined → `budget_declined`"; 20 min active wall clock (parked time excluded) → `timeout`. User: $10/month → "new runs refused".
- "Models without native tool calling are refused at startup." Model IDs only in config.
- P4 (`dev-sub`): "refuse if `ANTHROPIC_API_KEY` is set; bind `127.0.0.1` only; single user".
- "Exact schema is designed in the M0 plan and reviewed before migration (schemas are hard to reverse)." (SPEC §13)
- "DB roles: app role has only `INSERT` + `SELECT` on audit tables; `usta_purge` role deletes."
- Files UTF-8 without BOM. Azerbaijani text (`ə ğ ı ş İ ö ü ç`) must round-trip through every boundary.
- Neutral naming only (SPEC §19). Never commit `BLUEPRINT.md`, `.env`, or `az_token_benchmark.py`.
- gitleaks runs as a pre-commit hook and in CI.

## Plan Decisions (review these; they refine the spec)

1. **Core types are Pydantic v2 models.** Checkpoints and audit rows get JSON round-trips for free. Plain dataclasses would need hand-written (de)serialisation.
2. **`Budget` lives in `usta/core/budget.py`**, not `engines/own/`, because the worker and the future SDK engine also use it.
3. **The Anthropic adapter module is `usta/models/anthropic_adapter.py`** (the spec's module map says `anthropic.py`). The new name avoids confusion with the `anthropic` package.
4. **Tool names keep dots inside Usta** (`file.read`). Adapters encode `.` as `__` on the wire, because Anthropic and OpenAI-format tool names allow only `[a-zA-Z0-9_-]`. The registry rejects names that contain `__`.
5. **Provider thinking blocks are kept as `OpaqueBlock` and sent back unchanged.** Sonnet 5.5 always thinks, and its blocks must be echoed back. ⚠️ **Spec risk for M3:** Sonnet 5.5 and Opus 5.5 enforce a "preserved thinking" history-editing check for accounts created on or after 2026-08-31. Context layers 2 (clear) and 3 (compact) edit history, so ADR-017 must be revisited before M3.
6. **Server-side refusal `fallbacks` are deliberately not enabled.** They silently switch to another model, which violates P8 and ADR-035. A refusal ends the run with `stop_reason=error` and an explicit detail.
7. **`EnginePort` has only `run()`.** To resume, the worker loads the latest checkpoint and calls `run()`, and the loop first executes any tool calls that were left without results. M3 adds an SDK-specific resume if it needs one.
8. **M0 tool pipeline:** registry → JSON-schema validation → audit `intent` → execute → audit `done`. The verdict and taint stages (M2) and layer-1 offload (M3) slot in later. Every executed tool call gets `intent` and `done` rows; M2 only adds the resume check for `external_write`.
9. **Schema scope for M0:** `users`, `runs`, `run_checkpoints`, `model_calls`, `tool_calls`, `run_events`. There is no `todos` table, because todo state lives in the checkpoint JSON (SPEC §4.3: the checkpoint includes the todo). `grants`, `approvals`, `files`, `policy_verdicts` and `schedules` arrive with their milestones.
10. **Checkpoints append one row per step** rather than overwrite. Every step stays inspectable. Storage grows as O(steps × state), which is fine at 40 turns.
11. **Costs are `float` USD stored as double precision**, not `Decimal`. That precision is enough for budget accounting.
12. **The "2-tool task" uses `file.read` + `todo`**, both of which are spec tools. `file.list` / `file.search` / `file.write` come in M1. `file.read` truncates at 50k characters with a marker until layer-1 offload exists.
13. **The CLI uses `argparse`**, so it adds no dependency.
14. **Profiles are TOML files in `config/profiles/`.** Model caps and prices live in `config/models.toml`.
15. **Deferred, because the spec gives them no M0 slot:** the `local` profile and Ollama test, OTel → Langfuse (M3), the redactor and `usta purge` CLI, the planning reminder (M1), and API/UI (M4).
16. **The SDK's own retries are off** (`max_retries=0`), so that there is one retry policy, in the gateway, and every attempt is logged.

## Review Focus

These are the five input classes most likely to hurt a user that no spec bullet tests directly. Each one has a test in the task that owns the code:

1. **Azerbaijani text through every boundary** (checkpoint JSONB, audit rows, tool arguments, CLI output) must come back byte-identical and must not be printed as `\u` escapes. Tests: Task 2, Task 12, Task 14.
2. **Malformed or schema-violating tool arguments from the model** must become an error tool result that the model can react to. The run must not crash. Tests: Task 6, Task 8, Task 9.
3. **A tool name the model made up** must produce an error result listing the real tools, and the run must continue. Tests: Task 8, Task 9.
4. **The model stops on `max_tokens` or `refusal`** must end the run with an explicit `error` stop and a detail, and truncated tool calls must never execute. Test: Task 9.
5. **Paths that try to leave the workspace** (`..`, absolute paths, symlinks, user ids that would become odd directory names) must be refused with a clear message. Tests: Task 8, Task 12.

## File Map

```
pyproject.toml, uv.lock, .python-version, README.md, .env.example, alembic.ini
.github/workflows/ci.yml, .github/dependabot.yml
deploy/compose.dev.yml, deploy/postgres/init.sql
scripts/spike_gvisor.sh
config/models.toml, config/profiles/{test,dev-free,dev-api,dev-sub,prod}.toml
usta/core/      base.py messages.py model.py errors.py run.py events.py audit.py tools.py budget.py
usta/ports/     __init__.py (all Protocols + RunContext)
usta/models/    toolnames.py errors.py fake.py pricing.py caps.py anthropic_adapter.py litellm_adapter.py gateway.py
usta/tools/     registry.py pipeline.py builtin/{__init__,files,todo}.py
usta/engines/own/ prompt.py loop.py
usta/worker.py
usta/store/     tables.py pg.py migrations/{env.py,script.py.mako,versions/0001_initial.py}
usta/app/       config.py guards.py wiring.py
usta/cli.py
tests/          conftest.py fakes.py + mirrors of the package
```

---

### Task 0: WSL2 workspace and gVisor spike (M0 day 1)

Manual, not TDD. The deliverable is a committed spike script plus a recorded result in ADR-005 and SPEC §20 item 1.

**Files:**
- Create: `scripts/spike_gvisor.sh`
- Modify: `docs/adr/ADR-005-linux-first-gvisor.md` (Status line + a "Spike result" section), `SPEC.md` §20 item 1

- [ ] **Step 1: Enable systemd in WSL2 Ubuntu** (needed for the Docker Engine service). In Ubuntu, add the following to `/etc/wsl.conf`:

```ini
[boot]
systemd=true
```

Then, in Windows PowerShell, run `wsl --shutdown`, and reopen Ubuntu. Check: `systemctl is-system-running` prints `running` or `degraded`.

- [ ] **Step 2: Install Docker Engine inside Ubuntu (not Docker Desktop's integration).** Docker Desktop's daemon runs in its own VM, which cannot take the `runsc` runtime. In Docker Desktop → Settings → Resources → WSL integration, turn the integration **off** for this distro. Then:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"   # log out/in of the WSL shell afterwards
docker run --rm hello-world
```

Expected: the line "Hello from Docker!".

- [ ] **Step 3: Install gVisor and register it with Docker**

```bash
curl -fsSL https://gvisor.dev/archive.key | sudo gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" | sudo tee /etc/apt/sources.list.d/gvisor.list
sudo apt-get update && sudo apt-get install -y runsc
sudo runsc install
sudo systemctl restart docker
```

- [ ] **Step 4: Clone the repo into the Linux filesystem and install uv**

Docker bind mounts and file watching on `/mnt/c` are slow and break permissions, so the Windows folder is used only as the clone source.

```bash
mkdir -p ~/code && git clone /mnt/c/Users/Fariz.Akbarzada/Desktop/AI_Engineering/Usta ~/code/usta
cd ~/code/usta && git checkout -b m0-foundations
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12
cp /mnt/c/Users/Fariz.Akbarzada/Desktop/AI_Engineering/Usta/BLUEPRINT.md . 2>/dev/null || true   # private, gitignored
```

From here on, `~/code/usta` is the working copy. Run Claude Code from inside WSL in that directory.

- [ ] **Step 5: Write the spike script** `scripts/spike_gvisor.sh`:

```bash
#!/usr/bin/env bash
# M0 day-1 spike (SPEC §10, ADR-005): does gVisor (runsc) work in WSL2 with --network=none
# and the hardening flags the sandbox will use?
set -euo pipefail
IMG=python:3.12-slim

echo "== host kernel"; uname -r
echo "== runsc"; runsc --version | head -n 1
echo "== docker runtimes"; docker info --format '{{json .Runtimes}}'

echo "== 1. hello under runsc"
docker run --rm --runtime=runsc "$IMG" python -c "print('hello from gvisor')"

echo "== 2. sandbox kernel is gVisor's"
docker run --rm --runtime=runsc "$IMG" sh -c "dmesg 2>/dev/null | head -n 2 || true"

echo "== 3. no network with --network=none"
if docker run --rm --runtime=runsc --network=none "$IMG" \
    python -c "import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)"; then
  echo "FAIL: network reachable"; exit 1
else
  echo "OK: no network"
fi

echo "== 4. hardening flags accepted"
docker run --rm --runtime=runsc --network=none --cap-drop=ALL \
  --security-opt=no-new-privileges --read-only --tmpfs /tmp --user 65534:65534 \
  --memory=1g --cpus=1 --pids-limit=128 "$IMG" \
  python -c "import os; print('uid', os.getuid())"

echo "SPIKE PASSED"
```

- [ ] **Step 6: Run it**

Run: `chmod +x scripts/spike_gvisor.sh && ./scripts/spike_gvisor.sh 2>&1 | tee /tmp/spike.log`
Expected: `OK: no network`, then `uid 65534`, then `SPIKE PASSED`. Check 2 should print gVisor's boot lines (e.g. "Starting gVisor...").

- [ ] **Step 7: Record the result.** In `docs/adr/ADR-005-linux-first-gvisor.md`, change the line `Status: accepted (pending M0 spike)` to `Status: accepted (spike passed 2026-10-DD in WSL2)`, filling in the real date. If the spike failed, change it to `Status: accepted (spike failed in WSL2: gVisor on VM only; dev/prod parity broken)`. Then add the following at the end:

```markdown
## Spike result (M0 day 1)
- Kernel: <uname -r output>; runsc: <version line>
- hello / --network=none / hardening flags: <pass|fail each>
- Notes: <anything surprising, e.g. platform flag needed>
```

In SPEC.md §20, append the outcome to item 1, e.g. `1. gVisor-in-WSL2 spike result (M0 day 1). **Result: passed 2026-10-DD (ADR-005).**`

- [ ] **Step 8: Commit**

```bash
git add scripts/spike_gvisor.sh docs/adr/ADR-005-linux-first-gvisor.md SPEC.md
git commit -m "chore: gVisor-in-WSL2 spike script and result (ADR-005)"
```

- [ ] **Step 9 (needs Fariz's explicit OK: outward-facing): private GitHub remote for CI.** ADR-036 requires the manager's OK only for a *public* push, so use a private repo:

```bash
gh repo create usta --private --source . --remote origin --push
```

Before pushing, confirm that `git ls-files` lists neither `BLUEPRINT.md` nor `az_token_benchmark.py`.

---

### Task 1: Project scaffold, tooling and CI

**Files:**
- Create: `pyproject.toml`, `.python-version`, `README.md`, `.env.example`, `.github/workflows/ci.yml`, `.github/dependabot.yml`, `deploy/compose.dev.yml`, `deploy/postgres/init.sql`
- Create (empty packages): `usta/__init__.py`, `usta/core/__init__.py`, `usta/ports/__init__.py`, `usta/engines/__init__.py`, `usta/engines/own/__init__.py`, `usta/models/__init__.py`, `usta/tools/__init__.py`, `usta/tools/builtin/__init__.py`, `usta/store/__init__.py`, `usta/app/__init__.py`, `usta/worker.py`, `usta/cli.py`
- Test: `tests/__init__.py`, `tests/test_layout.py`

**Interfaces:**
- Produces: the package skeleton that every later task fills in, `uv run pytest`, `uv run lint-imports`, and a Postgres instance on `127.0.0.1:5432` with databases `usta` and `usta_test`.

- [ ] **Step 1: Write the failing test** `tests/test_layout.py` (plus an empty `tests/__init__.py`):

```python
import importlib

import pytest

LAYER_MODULES = [
    "usta.core",
    "usta.ports",
    "usta.engines.own",
    "usta.models",
    "usta.tools.builtin",
    "usta.store",
    "usta.app",
    "usta.worker",
    "usta.cli",
]


@pytest.mark.parametrize("module", LAYER_MODULES)
def test_layer_module_imports(module: str) -> None:
    importlib.import_module(module)
```

- [ ] **Step 2: Write `pyproject.toml`** (no package code yet):

```toml
[project]
name = "usta"
version = "0.1.0"
description = "Cowork-style work agent with its own harness: loop, tools, MCP, sandbox, evals"
readme = "README.md"
requires-python = ">=3.12,<3.13"
dependencies = [
    "alembic>=1.14,<2",
    "asyncpg>=0.30,<1",
    "jsonschema>=4.23,<5",
    "pydantic>=2.9,<3",
    "pydantic-settings>=2.6,<3",
    "sqlalchemy[asyncio]>=2.0.36,<2.1",
]

[dependency-groups]
dev = [
    "import-linter>=2.1",
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "ruff>=0.8",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["usta"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC"]
ignore = ["E501"]  # line length is the formatter's job

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
pythonpath = ["."]
testpaths = ["tests"]
addopts = "-m 'not live'"
markers = [
    "pg: needs Postgres (USTA_TEST_DATABASE_URL)",
    "live: calls a real model provider and spends quota; run with -m live",
]

[tool.importlinter]
root_package = "usta"
include_external_packages = true

[[tool.importlinter.contracts]]
name = "Layers (P5): core <- ports <- adapters/engine/tools/store/worker <- app <- cli"
type = "layers"
layers = [
    "usta.cli",
    "usta.app",
    "usta.engines | usta.models | usta.tools | usta.store | usta.worker",
    "usta.ports",
    "usta.core",
]

[[tool.importlinter.contracts]]
name = "LiteLLM only in its adapter (F8, ADR-020)"
type = "forbidden"
source_modules = ["usta"]
forbidden_modules = ["litellm"]
allow_indirect_imports = true
ignore_imports = ["usta.models.litellm_adapter -> litellm"]

[[tool.importlinter.contracts]]
name = "Anthropic SDK only in its adapter (ADR-020)"
type = "forbidden"
source_modules = ["usta"]
forbidden_modules = ["anthropic"]
allow_indirect_imports = true
ignore_imports = ["usta.models.anthropic_adapter -> anthropic"]
```

Also write `.python-version` containing `3.12`.

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv sync && uv run pytest tests/test_layout.py -q`
Expected: 9 failures with `ModuleNotFoundError: No module named 'usta'`.

- [ ] **Step 4: Create the package skeleton.** Each `__init__.py` listed under Files is created empty. `usta/worker.py` contains only a docstring:

```python
"""In-process run worker (ADR-014). Filled in by Task 10."""
```

`usta/cli.py` contains only a docstring:

```python
"""Usta command line. Filled in by Task 14."""
```

- [ ] **Step 5: Run the tests and the import contracts**

Run: `uv run pytest -q && uv run lint-imports`
Expected: `9 passed`. lint-imports reports `Contracts: 3 kept, 0 broken.`

- [ ] **Step 6: Dev Postgres.** `deploy/compose.dev.yml`:

```yaml
# Dev/test Postgres. Passwords here are local dev values, not secrets.
services:
  postgres:
    image: postgres:17
    environment:
      POSTGRES_USER: usta
      POSTGRES_PASSWORD: usta_owner_dev
      POSTGRES_DB: usta
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./postgres/init.sql:/docker-entrypoint-initdb.d/10-init.sql:ro
volumes:
  pgdata:
```

`deploy/postgres/init.sql`:

```sql
-- Runs once on first start. Group roles are also created by migration 0001 (IF NOT EXISTS),
-- so order does not matter. Login passwords are local dev values, not secrets.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'usta_app') THEN CREATE ROLE usta_app NOLOGIN; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'usta_purge') THEN CREATE ROLE usta_purge NOLOGIN; END IF;
END $$;
CREATE ROLE usta_app_login LOGIN PASSWORD 'usta_app_dev' IN ROLE usta_app;
CREATE DATABASE usta_test OWNER usta;
```

`.env.example` (no secrets):

```bash
# Copy to .env (gitignored) and load with: set -a; source .env; set +a
USTA_PROFILE=dev-free
USTA_USER=fariz
# App connects as the restricted app role; migrations and tests use the owner.
USTA_DATABASE_URL=postgresql+asyncpg://usta_app_login:usta_app_dev@127.0.0.1:5432/usta
USTA_MIGRATION_DATABASE_URL=postgresql+asyncpg://usta:usta_owner_dev@127.0.0.1:5432/usta
USTA_TEST_DATABASE_URL=postgresql+asyncpg://usta:usta_owner_dev@127.0.0.1:5432/usta_test
GEMINI_API_KEY=
ANTHROPIC_API_KEY=
```

Run: `docker compose -f deploy/compose.dev.yml up -d && docker compose -f deploy/compose.dev.yml exec postgres psql -U usta -c '\l'`
Expected: the database list includes `usta` and `usta_test`.

- [ ] **Step 7: CI and Dependabot.** `.github/workflows/ci.yml`:

```yaml
name: ci
on: [push, pull_request]

jobs:
  gitleaks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

  t1:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:17
        env:
          POSTGRES_USER: usta
          POSTGRES_PASSWORD: usta_ci
          POSTGRES_DB: usta_test
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U usta" --health-interval 5s
          --health-timeout 5s --health-retries 10
    env:
      USTA_TEST_DATABASE_URL: postgresql+asyncpg://usta:usta_ci@localhost:5432/usta_test
      USTA_MIGRATION_DATABASE_URL: postgresql+asyncpg://usta:usta_ci@localhost:5432/usta_test
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --locked
      - run: uv run ruff format --check .
      - run: uv run ruff check .
      - run: uv run lint-imports
      - run: uv run pytest -q --tb=short
```

`.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: "uv"
    directory: "/"
    schedule: { interval: "weekly" }
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule: { interval: "weekly" }
```

- [ ] **Step 8: README.** Write `README.md`:

```markdown
# Usta

A Cowork-style work agent with its own harness: agent loop, tool pipeline, MCP, gVisor sandbox
and evals. Design: [SPEC.md](SPEC.md) · decisions: [docs/adr](docs/adr) · terms: [CONTEXT.md](CONTEXT.md).

## Develop (WSL2 Ubuntu)

    uv sync
    cp .env.example .env            # fill in keys; .env is gitignored
    set -a; source .env; set +a
    docker compose -f deploy/compose.dev.yml up -d
    uv run pytest -q                # T1 (fake model, real Postgres)
    uv run lint-imports             # P5 dependency rule
```

- [ ] **Step 9: Format, verify, commit**

```bash
uv run ruff check --fix . && uv run ruff format . && uv run lint-imports && uv run pytest -q
git add pyproject.toml uv.lock .python-version README.md .env.example .github deploy usta tests
git commit -m "chore: project scaffold, import contracts, CI, dev Postgres"
```

If a remote exists, run `git push -u origin m0-foundations` and confirm that both CI jobs pass.

---

### Task 2: Core types, ports and in-memory test doubles

**Files:**
- Create: `usta/core/base.py`, `usta/core/messages.py`, `usta/core/model.py`, `usta/core/errors.py`, `usta/core/run.py`, `usta/core/events.py`, `usta/core/audit.py`, `usta/core/tools.py`, `usta/core/budget.py`
- Modify: `usta/ports/__init__.py`
- Create: `tests/fakes.py`
- Test: `tests/core/__init__.py`, `tests/core/test_messages.py`, `tests/core/test_run.py`, `tests/core/test_budget.py`, `tests/test_fakes.py`

**Interfaces:**
- Produces (exact names that every later task uses):
  - `usta.core.base.Frozen`, a frozen Pydantic base model
  - `usta.core.messages`: `TextBlock(text)`, `ToolCall(id, name, input, input_error=None)`, `ToolResult(call_id, content, is_error=False)`, `OpaqueBlock(provider, data)`, `Message(role, content: tuple)`, with `Message.user_text(str)`, `.text()`, `.tool_calls()`, `.tool_results()`
  - `usta.core.model`: `Role = Literal["main","light"]`, `ModelStop`, `ModelCaps`, `ToolSpec(name, description, input_schema)`, `SystemBlock(text, cache=False)`, `ModelRequest(role, system, messages, tools=(), prompt_version, run_id=None, user_id=None, max_output_tokens=None)`, `Usage(input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)`, `ModelResponse(message, usage, stop, model, cost_usd=0.0)` with `.tool_calls()`
  - `usta.core.errors`: `UstaError`, `ConfigError`, `ProviderError`, `TransientProviderError`, `ProviderRateLimited`, `ProviderQuotaError`, `ProviderUnavailable`, `UserBudgetExceeded`, `UnknownUser`, `ToolInputError`
  - `usta.core.run`: `RunStatus`, `PARKED_STATUSES`, `StopReason`, `TodoItem`, `PendingQuestion(kind="budget", text)`, `RunState` with `.new(...)`, `.record(resp)`, `.append_tool_results(list)`, `.pending_tool_calls()`, `.park(status, q)`, `.finish(reason, detail=None)`, `.final_text()`, `.is_finished`, `.is_parked`
  - `usta.core.events.Event(run_id, type, data)` with `Event.finished(run)` and `Event.parked(run)`
  - `usta.core.audit`: `ModelCallRecord`, `ToolCallRecord`
  - `usta.core.tools.ToolOutcome(result, event=None)`
  - `usta.core.budget`: `Budget(max_turns=40, cost_step_usd=0.5, max_active_seconds=1200)`, whose `.check(run)` returns `"max_turns" | "timeout" | "cost" | None`
  - `usta.ports`: `ModelPort`, `ModelGateway`, `AuditSink`, `RunStore`, `ToolPipelinePort`, `RunContext(models, tools, store)`, `EnginePort`
  - `tests.fakes`: `InMemoryStore` (RunStore + AuditSink) and `FakeClock`

- [ ] **Step 1: Write the failing tests.** Create an empty `tests/core/__init__.py`. Then `tests/core/test_messages.py`:

```python
from usta.core.messages import Message, OpaqueBlock, TextBlock, ToolCall, ToolResult

AZ = "İSTİQAMƏT: Gəncə, IŞIQ — ğ ş ı ö ü ç ə"


def test_message_json_round_trip_keeps_block_types_and_azerbaijani_text() -> None:
    msg = Message(
        role="assistant",
        content=(
            TextBlock(text=AZ),
            ToolCall(id="c1", name="file.read", input={"path": "files/qeyd.txt"}),
            OpaqueBlock(provider="anthropic", data={"type": "thinking", "thinking": "", "signature": "s"}),
        ),
    )
    again = Message.model_validate_json(msg.model_dump_json())
    assert again == msg
    assert again.text() == AZ
    assert [c.name for c in again.tool_calls()] == ["file.read"]


def test_user_text_and_tool_results_helpers() -> None:
    assert Message.user_text("salam").content == (TextBlock(text="salam"),)
    msg = Message(role="user", content=(ToolResult(call_id="c1", content="ok"),))
    assert msg.tool_results() == [ToolResult(call_id="c1", content="ok")]
    assert msg.text() == ""
```

`tests/core/test_run.py`:

```python
import pytest

from usta.core.events import Event
from usta.core.messages import Message, TextBlock, ToolCall, ToolResult
from usta.core.model import ModelResponse, Usage
from usta.core.run import PendingQuestion, RunState, RunStatus, StopReason


def make_run() -> RunState:
    return RunState.new(id="r1", user_id="u1", task="Hesabat hazırla", engine="own", cost_cap_usd=0.5)


def assistant(*blocks) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content=blocks),
        usage=Usage(input_tokens=10, output_tokens=5),
        stop="end_turn",
        model="m",
        cost_usd=0.25,
    )


def test_new_run_is_queued_with_task_as_first_message() -> None:
    run = make_run()
    assert run.status == RunStatus.QUEUED
    assert run.messages == [Message.user_text("Hesabat hazırla")]
    assert (run.turns, run.cost_usd, run.stop_reason) == (0, 0.0, None)


def test_record_adds_message_turn_and_cost() -> None:
    run = make_run()
    run.record(assistant(TextBlock(text="hazır")))
    assert (run.turns, run.cost_usd) == (1, 0.25)
    assert run.final_text() == "hazır"


def test_pending_tool_calls_only_when_last_message_is_assistant_with_calls() -> None:
    run = make_run()
    assert run.pending_tool_calls() == []
    call = ToolCall(id="c1", name="todo", input={})
    run.record(assistant(call))
    assert run.pending_tool_calls() == [call]
    run.append_tool_results([ToolResult(call_id="c1", content="ok")])
    assert run.pending_tool_calls() == []


def test_append_tool_results_uses_one_user_message() -> None:
    run = make_run()
    run.append_tool_results([ToolResult(call_id="a", content="1"), ToolResult(call_id="b", content="2")])
    assert run.messages[-1].role == "user"
    assert [r.call_id for r in run.messages[-1].tool_results()] == ["a", "b"]


def test_park_and_finish() -> None:
    run = make_run()
    with pytest.raises(ValueError):
        run.park(RunStatus.RUNNING, PendingQuestion(kind="budget", text="?"))
    run.park(RunStatus.AWAITING_USER, PendingQuestion(kind="budget", text="Davam?"))
    assert run.is_parked and run.pending is not None
    run.finish(StopReason.BUDGET_DECLINED, "no")
    assert run.is_finished and not run.is_parked and run.pending is None
    assert Event.finished(run).data == {
        "stop_reason": "budget_declined",
        "detail": "no",
        "turns": 0,
        "cost_usd": 0.0,
    }


def test_state_json_round_trip() -> None:
    run = make_run()
    run.record(assistant(ToolCall(id="c1", name="file.read", input={"path": "files/ə.txt"})))
    again = RunState.model_validate_json(run.model_dump_json())
    assert again == run
    assert again.status == RunStatus.QUEUED
```

`tests/core/test_budget.py`:

```python
import pytest

from usta.core.budget import Budget
from usta.core.run import RunState


@pytest.mark.parametrize(
    ("turns", "active", "cost", "expected"),
    [
        (0, 0.0, 0.0, None),
        (40, 0.0, 0.0, "max_turns"),
        (0, 1200.0, 0.0, "timeout"),
        (0, 0.0, 0.5, "cost"),
        (40, 1200.0, 0.5, "max_turns"),
    ],
)
def test_budget_check(turns: int, active: float, cost: float, expected: str | None) -> None:
    run = RunState.new(id="r", user_id="u", task="t", engine="own", cost_cap_usd=0.5)
    run.turns, run.active_seconds, run.cost_usd = turns, active, cost
    assert Budget().check(run) == expected
```

`tests/test_fakes.py`:

```python
import pytest

from usta.core.audit import ModelCallRecord
from usta.core.model import Usage
from usta.core.run import RunState, RunStatus
from tests.fakes import InMemoryStore


async def test_in_memory_store_round_trips_state_like_postgres() -> None:
    store = InMemoryStore()
    run = RunState.new(id="r1", user_id="u1", task="ə", engine="own", cost_cap_usd=0.5)
    await store.create(run)
    run.status = RunStatus.RUNNING
    await store.checkpoint(run)
    loaded = await store.load("r1")
    assert loaded == run and loaded is not run
    assert await store.ids_with_status(RunStatus.RUNNING) == ["r1"]
    assert await store.cancel_requested("r1") is False
    await store.request_cancel("r1")
    assert await store.cancel_requested("r1") is True


async def test_in_memory_month_cost_sums_model_calls_per_user() -> None:
    store = InMemoryStore()
    for user, cost in [("u1", 0.1), ("u1", 0.2), ("u2", 5.0)]:
        await store.model_call(
            ModelCallRecord(
                run_id="r", user_id=user, role="main", provider="fake", model="m",
                prompt_version="p", attempt=1, request={}, response=None, error=None,
                usage=Usage(), cost_usd=cost, latency_ms=1,
            )
        )
    assert await store.user_month_cost("u1") == pytest.approx(0.3)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core tests/test_fakes.py -q`
Expected: collection errors, e.g. `ModuleNotFoundError: No module named 'usta.core.messages'`.

- [ ] **Step 3: Implement the core modules.**

`usta/core/base.py`:

```python
from pydantic import BaseModel, ConfigDict


class Frozen(BaseModel):
    """Immutable domain value."""

    model_config = ConfigDict(frozen=True)
```

`usta/core/messages.py`:

```python
"""Usta's own message types. No provider shape reaches the loop (ADR-020)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from usta.core.base import Frozen


class TextBlock(Frozen):
    type: Literal["text"] = "text"
    text: str


class ToolCall(Frozen):
    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    input: dict[str, Any]
    input_error: str | None = None  # provider sent arguments we could not parse


class ToolResult(Frozen):
    type: Literal["tool_result"] = "tool_result"
    call_id: str
    content: str
    is_error: bool = False


class OpaqueBlock(Frozen):
    """Provider-specific block echoed back unchanged (e.g. Anthropic thinking blocks)."""

    type: Literal["opaque"] = "opaque"
    provider: str
    data: dict[str, Any]


ContentBlock = Annotated[
    TextBlock | ToolCall | ToolResult | OpaqueBlock, Field(discriminator="type")
]


class Message(Frozen):
    role: Literal["user", "assistant"]
    content: tuple[ContentBlock, ...]

    @classmethod
    def user_text(cls, text: str) -> Message:
        return cls(role="user", content=(TextBlock(text=text),))

    def text(self) -> str:
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))

    def tool_calls(self) -> list[ToolCall]:
        return [b for b in self.content if isinstance(b, ToolCall)]

    def tool_results(self) -> list[ToolResult]:
        return [b for b in self.content if isinstance(b, ToolResult)]
```

`usta/core/model.py`:

```python
"""Model-layer value types shared by every adapter (SPEC §3.3, ADR-021)."""

from typing import Any, Literal

from usta.core.base import Frozen
from usta.core.messages import Message, ToolCall

Role = Literal["main", "light"]
ModelStop = Literal["end_turn", "tool_use", "max_tokens", "refusal", "other"]


class ModelCaps(Frozen):
    context_tokens: int
    max_output_tokens: int
    prompt_cache: Literal["explicit", "automatic", "none"]
    parallel_tool_calls: bool
    native_tools: bool  # False -> startup refuses the model


class ToolSpec(Frozen):
    name: str
    description: str
    input_schema: dict[str, Any]


class SystemBlock(Frozen):
    text: str
    cache: bool = False  # cache marker after this block (R10)


class ModelRequest(Frozen):
    role: Role
    system: tuple[SystemBlock, ...]
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()
    prompt_version: str
    run_id: str | None = None
    user_id: str | None = None
    max_output_tokens: int | None = None  # None -> the role's configured default


class Usage(Frozen):
    input_tokens: int = 0  # uncached input (Anthropic semantics)
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class ModelResponse(Frozen):
    message: Message  # role == "assistant"
    usage: Usage
    stop: ModelStop
    model: str
    cost_usd: float = 0.0  # set by the gateway from the price table (P7)

    def tool_calls(self) -> list[ToolCall]:
        return self.message.tool_calls()
```

`usta/core/errors.py`:

```python
class UstaError(Exception):
    """Expected, user-facing failure (printed without a traceback)."""


class ConfigError(UstaError):
    """Startup refused: profile, model catalog or environment is invalid."""


class ProviderError(UstaError):
    """Model provider failed; not retryable."""


class TransientProviderError(ProviderError):
    """Retryable: timeouts, 5xx, overload, connection errors."""


class ProviderRateLimited(TransientProviderError):
    """HTTP 429. Retried; still limited after all attempts -> ProviderQuotaError."""


class ProviderQuotaError(ProviderError):
    """Account quota or billing limit reached (stop_reason=provider_quota)."""


class ProviderUnavailable(ProviderError):
    """Circuit breaker is open for this provider."""


class UserBudgetExceeded(UstaError):
    """The user's monthly cost cap is reached; new runs are refused."""


class UnknownUser(UstaError):
    """A run was submitted for a user id that does not exist."""


class ToolInputError(UstaError):
    """Tool arguments are invalid; reported to the model as an error result."""
```

`usta/core/run.py`:

```python
"""Run state: everything a checkpoint stores (SPEC §4.2, §4.3)."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from usta.core.messages import Message, ToolCall, ToolResult
from usta.core.model import ModelResponse


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_USER = "awaiting_user"
    UNKNOWN_OUTCOME = "unknown_outcome"
    FINISHED = "finished"


PARKED_STATUSES = frozenset(
    {RunStatus.AWAITING_APPROVAL, RunStatus.AWAITING_USER, RunStatus.UNKNOWN_OUTCOME}
)


class StopReason(StrEnum):
    DONE = "done"
    VERIFICATION_FAILED = "verification_failed"
    MAX_TURNS = "max_turns"
    BUDGET_DECLINED = "budget_declined"
    TIMEOUT = "timeout"
    PROVIDER_QUOTA = "provider_quota"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    ERROR = "error"


class TodoItem(BaseModel):
    content: str
    status: Literal["pending", "in_progress", "done"]


class PendingQuestion(BaseModel):
    kind: Literal["budget"]  # M2 adds "ask_user"
    text: str


class RunState(BaseModel):
    schema_version: int = 1
    id: str
    user_id: str
    task: str
    engine: str
    cost_cap_usd: float
    status: RunStatus = RunStatus.QUEUED
    stop_reason: StopReason | None = None
    stop_detail: str | None = None
    messages: list[Message] = Field(default_factory=list)
    turns: int = 0
    cost_usd: float = 0.0
    active_seconds: float = 0.0
    todo: list[TodoItem] = Field(default_factory=list)
    pending: PendingQuestion | None = None

    @classmethod
    def new(
        cls, *, id: str, user_id: str, task: str, engine: str, cost_cap_usd: float
    ) -> RunState:
        return cls(
            id=id,
            user_id=user_id,
            task=task,
            engine=engine,
            cost_cap_usd=cost_cap_usd,
            messages=[Message.user_text(task)],
        )

    @property
    def is_finished(self) -> bool:
        return self.status == RunStatus.FINISHED

    @property
    def is_parked(self) -> bool:
        return self.status in PARKED_STATUSES

    def record(self, resp: ModelResponse) -> None:
        self.messages.append(resp.message)
        self.turns += 1
        self.cost_usd += resp.cost_usd

    def append_tool_results(self, results: list[ToolResult]) -> None:
        self.messages.append(Message(role="user", content=tuple(results)))

    def pending_tool_calls(self) -> list[ToolCall]:
        """Calls of the last assistant message that have no results yet (crash between checkpoints)."""
        if not self.messages or self.messages[-1].role != "assistant":
            return []
        return self.messages[-1].tool_calls()

    def park(self, status: RunStatus, question: PendingQuestion) -> None:
        if status not in PARKED_STATUSES:
            raise ValueError(f"{status} is not a parked status")
        self.status = status
        self.pending = question

    def finish(self, reason: StopReason, detail: str | None = None) -> None:
        self.status = RunStatus.FINISHED
        self.stop_reason = reason
        self.stop_detail = detail
        self.pending = None

    def final_text(self) -> str:
        for msg in reversed(self.messages):
            if msg.role == "assistant":
                return msg.text()
        return ""
```

`usta/core/events.py`:

```python
"""Run events: streamed to the CLI/UI and stored in run_events (SPEC §13)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from usta.core.base import Frozen
from usta.core.run import RunState

EventType = Literal[
    "run_started",
    "model_call",
    "tool_call",
    "tool_result",
    "todo_updated",
    "step_done",
    "parked",
    "finished",
]


class Event(Frozen):
    run_id: str
    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def finished(cls, run: RunState) -> Event:
        return cls(
            run_id=run.id,
            type="finished",
            data={
                "stop_reason": run.stop_reason.value if run.stop_reason else None,
                "detail": run.stop_detail,
                "turns": run.turns,
                "cost_usd": round(run.cost_usd, 6),
            },
        )

    @classmethod
    def parked(cls, run: RunState) -> Event:
        return cls(
            run_id=run.id,
            type="parked",
            data={
                "status": run.status.value,
                "question": run.pending.model_dump() if run.pending else None,
            },
        )
```

`usta/core/audit.py`:

```python
"""Append-only audit records (P7, ADR-029)."""

from typing import Any, Literal

from usta.core.base import Frozen
from usta.core.model import Usage


class ModelCallRecord(Frozen):
    run_id: str | None
    user_id: str | None
    role: str
    provider: str
    model: str
    prompt_version: str
    attempt: int
    request: dict[str, Any]
    response: dict[str, Any] | None
    error: str | None
    usage: Usage
    cost_usd: float
    latency_ms: int


class ToolCallRecord(Frozen):
    run_id: str
    user_id: str
    call_id: str
    tool: str
    phase: Literal["intent", "done"]
    input: dict[str, Any]
    output: str | None = None
    is_error: bool | None = None
    latency_ms: int | None = None
```

`usta/core/tools.py`:

```python
from usta.core.base import Frozen
from usta.core.events import Event
from usta.core.messages import ToolResult


class ToolOutcome(Frozen):
    """What the tool pipeline returns to an engine. M2 adds a parked flag for approvals."""

    result: ToolResult
    event: Event | None = None
```

`usta/core/budget.py`:

```python
"""Run budgets shared by both engines (SPEC §15.2, ADR-035)."""

from typing import Literal

from usta.core.base import Frozen
from usta.core.run import RunState

BudgetLimit = Literal["max_turns", "timeout", "cost"]


class Budget(Frozen):
    max_turns: int = 40
    cost_step_usd: float = 0.50
    max_active_seconds: float = 1200.0

    def check(self, run: RunState) -> BudgetLimit | None:
        if run.turns >= self.max_turns:
            return "max_turns"
        if run.active_seconds >= self.max_active_seconds:
            return "timeout"
        if run.cost_usd >= run.cost_cap_usd:
            return "cost"
        return None
```

- [ ] **Step 4: Ports.** Replace `usta/ports/__init__.py`:

```python
"""Protocols between the core and everything else (P5). Only usta.app wires concrete classes."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from usta.core.audit import ModelCallRecord, ToolCallRecord
from usta.core.events import Event
from usta.core.messages import ToolCall
from usta.core.model import ModelCaps, ModelRequest, ModelResponse, ToolSpec
from usta.core.run import RunState, RunStatus
from usta.core.tools import ToolOutcome


class ModelPort(Protocol):
    provider: str
    model_id: str
    caps: ModelCaps

    async def complete(self, req: ModelRequest) -> ModelResponse: ...


class ModelGateway(Protocol):
    """What engines call: routes by req.role; logging, retries and cost happen behind it."""

    async def complete(self, req: ModelRequest) -> ModelResponse: ...


class AuditSink(Protocol):
    async def model_call(self, rec: ModelCallRecord) -> None: ...
    async def tool_call(self, rec: ToolCallRecord) -> None: ...


class RunStore(Protocol):
    async def create(self, run: RunState) -> None: ...
    async def load(self, run_id: str) -> RunState: ...
    async def checkpoint(self, run: RunState) -> None: ...
    async def ids_with_status(self, *statuses: RunStatus) -> list[str]: ...
    async def request_cancel(self, run_id: str) -> None: ...
    async def cancel_requested(self, run_id: str) -> bool: ...
    async def append_event(self, event: Event, user_id: str) -> None: ...
    async def user_month_cost(self, user_id: str) -> float: ...


class ToolPipelinePort(Protocol):
    def specs(self) -> tuple[ToolSpec, ...]: ...
    async def handle(self, call: ToolCall, run: RunState) -> ToolOutcome: ...


@dataclass(frozen=True)
class RunContext:
    """What an engine gets; identical for both engines (SPEC §3.3). Skills (M1) and the
    run token (M2) are added when they exist."""

    models: ModelGateway
    tools: ToolPipelinePort
    store: RunStore


class EnginePort(Protocol):
    def run(self, run: RunState, ctx: RunContext) -> AsyncIterator[Event]: ...
```

- [ ] **Step 5: Test doubles.** Create `tests/fakes.py`:

```python
"""Test doubles. Never imported by usta/ (P8)."""

from usta.core.audit import ModelCallRecord, ToolCallRecord
from usta.core.events import Event
from usta.core.run import RunState, RunStatus


class InMemoryStore:
    """RunStore + AuditSink double. Stores checkpoints as JSON, like Postgres does."""

    def __init__(self) -> None:
        self.checkpoints: dict[str, list[dict]] = {}
        self.cancel: set[str] = set()
        self.events: list[Event] = []
        self.model_calls: list[ModelCallRecord] = []
        self.tool_calls: list[ToolCallRecord] = []

    async def create(self, run: RunState) -> None:
        self.checkpoints[run.id] = [run.model_dump(mode="json")]

    async def load(self, run_id: str) -> RunState:
        return RunState.model_validate(self.checkpoints[run_id][-1])

    async def checkpoint(self, run: RunState) -> None:
        self.checkpoints[run.id].append(run.model_dump(mode="json"))

    async def ids_with_status(self, *statuses: RunStatus) -> list[str]:
        return [rid for rid, cps in self.checkpoints.items() if cps[-1]["status"] in statuses]

    async def request_cancel(self, run_id: str) -> None:
        self.cancel.add(run_id)

    async def cancel_requested(self, run_id: str) -> bool:
        return run_id in self.cancel

    async def append_event(self, event: Event, user_id: str) -> None:
        self.events.append(event)

    async def user_month_cost(self, user_id: str) -> float:
        return sum(r.cost_usd for r in self.model_calls if r.user_id == user_id)

    async def model_call(self, rec: ModelCallRecord) -> None:
        self.model_calls.append(rec)

    async def tool_call(self, rec: ToolCallRecord) -> None:
        self.tool_calls.append(rec)


class FakeClock:
    """Monotonic clock for tests: each call returns `now`, then advances it by `step`."""

    def __init__(self, step: float = 0.0) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        t = self.now
        self.now += self.step
        return t
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/core tests/test_fakes.py -q && uv run lint-imports`
Expected: all tests pass, and `Contracts: 3 kept`.

- [ ] **Step 7: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add usta/core usta/ports tests
git commit -m "feat(core): domain types, run state, budget, ports and test doubles"
```

---

### Task 3: Tool-name codec, provider error mapping, fake adapter, adapter contract

**Files:**
- Create: `usta/models/toolnames.py`, `usta/models/errors.py`, `usta/models/fake.py`
- Test: `tests/models/__init__.py`, `tests/models/contract.py` (shared helper, not collected), `tests/models/test_toolnames.py`, `tests/models/test_fake.py`

**Interfaces:**
- Consumes: the core types from Task 2.
- Produces:
  - `encode(name) -> str` / `decode(wire) -> str`
  - `map_status(status: int | None, message: str) -> ProviderError`
  - `FakeModel(script=(), *, model_id="fake-model", caps=DEFAULT_CAPS)` with a `.requests` list. A script step can be a `ModelResponse`, an exception, or a callable `(ModelRequest) -> ModelResponse`.
  - `reply(text, *, usage=...) -> ModelResponse` and `call(name, input, *, id=None, text="", usage=...) -> ModelResponse`
  - `tests.models.contract.CONTRACT_REQUEST` and `assert_contract_response(resp)`, which Tasks 5 and 6 reuse

- [ ] **Step 1: Write the failing tests.** Create an empty `tests/models/__init__.py`. Then `tests/models/contract.py`:

```python
"""Shared adapter contract (SPEC §5): messages + tools + tool results + usage incl. cache
tokens round-trip. Each adapter test serves wire data equivalent to CONTRACT_RESPONSE."""

from usta.core.messages import Message, TextBlock, ToolCall, ToolResult
from usta.core.model import ModelRequest, ModelResponse, SystemBlock, ToolSpec, Usage

READ_SPEC = ToolSpec(
    name="file.read",
    description="Read a file.",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
)

CONTRACT_REQUEST = ModelRequest(
    role="main",
    system=(SystemBlock(text="You are Usta.", cache=True),),
    messages=(
        Message.user_text("Qeydləri oxu."),
        Message(
            role="assistant",
            content=(ToolCall(id="toolu_1", name="file.read", input={"path": "files/a.txt"}),),
        ),
        Message(role="user", content=(ToolResult(call_id="toolu_1", content="İSTİQAMƏT: Bakı"),)),
    ),
    tools=(READ_SPEC,),
    prompt_version="contract-v1",
)

CONTRACT_RESPONSE = ModelResponse(
    message=Message(
        role="assistant",
        content=(
            TextBlock(text="Oxuyuram."),
            ToolCall(id="toolu_2", name="file.read", input={"path": "files/qeyd.txt"}),
        ),
    ),
    usage=Usage(input_tokens=12, output_tokens=7, cache_read_tokens=900, cache_write_tokens=100),
    stop="tool_use",
    model="contract-model",
)


def assert_contract_response(resp: ModelResponse) -> None:
    assert resp.message.role == "assistant"
    assert resp.message.text() == "Oxuyuram."
    [call] = resp.tool_calls()
    assert (call.id, call.name, call.input, call.input_error) == (
        "toolu_2",
        "file.read",
        {"path": "files/qeyd.txt"},
        None,
    )
    assert resp.stop == "tool_use"
    assert resp.usage == Usage(
        input_tokens=12, output_tokens=7, cache_read_tokens=900, cache_write_tokens=100
    )
```

`tests/models/test_toolnames.py`:

```python
import pytest

from usta.core.errors import ProviderError, ProviderQuotaError, ProviderRateLimited, TransientProviderError
from usta.models.errors import map_status
from usta.models.toolnames import decode, encode


def test_dots_are_encoded_for_the_wire_and_decoded_back() -> None:
    assert encode("file.read") == "file__read"
    assert decode("file__read") == "file.read"
    assert decode(encode("fleet.fuel_report")) == "fleet.fuel_report"


def test_names_with_double_underscore_are_refused() -> None:
    with pytest.raises(ValueError):
        encode("bad__name")


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (402, ProviderQuotaError),
        (429, ProviderRateLimited),
        (408, TransientProviderError),
        (409, TransientProviderError),
        (500, TransientProviderError),
        (529, TransientProviderError),
        (400, ProviderError),
        (401, ProviderError),
        (None, ProviderError),
    ],
)
def test_map_status(status: int | None, error: type) -> None:
    assert type(map_status(status, "boom")) is error
```

`tests/models/test_fake.py`:

```python
import pytest

from usta.core.errors import ProviderQuotaError
from usta.models.fake import FakeModel, call, reply
from tests.models.contract import CONTRACT_REQUEST, CONTRACT_RESPONSE, assert_contract_response


async def test_fake_meets_the_contract_and_records_requests() -> None:
    model = FakeModel([CONTRACT_RESPONSE])
    assert_contract_response(await model.complete(CONTRACT_REQUEST))
    assert model.requests == [CONTRACT_REQUEST]


async def test_script_can_raise_and_compute() -> None:
    model = FakeModel([ProviderQuotaError("cap"), lambda req: reply(req.prompt_version)])
    with pytest.raises(ProviderQuotaError):
        await model.complete(CONTRACT_REQUEST)
    assert (await model.complete(CONTRACT_REQUEST)).message.text() == "contract-v1"


async def test_exhausted_script_fails_loudly() -> None:
    with pytest.raises(AssertionError, match="script exhausted"):
        await FakeModel([]).complete(CONTRACT_REQUEST)


def test_call_helper_builds_a_tool_use_response_with_unique_ids() -> None:
    a, b = call("todo", {"items": []}), call("todo", {"items": []})
    assert a.stop == "tool_use"
    assert a.tool_calls()[0].name == "todo"
    assert a.tool_calls()[0].id != b.tool_calls()[0].id
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/models -q`
Expected: `ModuleNotFoundError: No module named 'usta.models.toolnames'` (and the same for fake).

- [ ] **Step 3: Implement.** `usta/models/toolnames.py`:

```python
"""Usta tool names use dots (file.read); Anthropic/OpenAI wire names allow only [a-zA-Z0-9_-]."""


def encode(name: str) -> str:
    if "__" in name:
        raise ValueError(f"tool name {name!r} must not contain '__'")
    return name.replace(".", "__")


def decode(wire_name: str) -> str:
    return wire_name.replace("__", ".")
```

`usta/models/errors.py`:

```python
"""Map provider HTTP status codes to Usta errors. Shared by adapters, so it is not an adapter."""

from usta.core.errors import (
    ProviderError,
    ProviderQuotaError,
    ProviderRateLimited,
    TransientProviderError,
)


def map_status(status: int | None, message: str) -> ProviderError:
    if status == 402:
        return ProviderQuotaError(message)
    if status == 429:
        return ProviderRateLimited(message)
    if status in (408, 409) or (status is not None and status >= 500):
        return TransientProviderError(message)
    return ProviderError(message)
```

`usta/models/fake.py`:

```python
"""Scripted model for the `test` profile only. Startup guards refuse it elsewhere (P8)."""

import itertools
from collections import deque
from collections.abc import Callable, Iterable
from typing import Any

from usta.core.messages import Message, TextBlock, ToolCall
from usta.core.model import ModelCaps, ModelRequest, ModelResponse, Usage

DEFAULT_CAPS = ModelCaps(
    context_tokens=200_000,
    max_output_tokens=8_192,
    prompt_cache="none",
    parallel_tool_calls=True,
    native_tools=True,
)
DEFAULT_USAGE = Usage(input_tokens=10, output_tokens=5)

ScriptStep = ModelResponse | BaseException | Callable[[ModelRequest], ModelResponse]
_ids = itertools.count(1)


class FakeModel:
    provider = "fake"

    def __init__(
        self,
        script: Iterable[ScriptStep] = (),
        *,
        model_id: str = "fake-model",
        caps: ModelCaps = DEFAULT_CAPS,
    ) -> None:
        self.model_id = model_id
        self.caps = caps
        self.requests: list[ModelRequest] = []
        self._script: deque[ScriptStep] = deque(script)

    async def complete(self, req: ModelRequest) -> ModelResponse:
        self.requests.append(req)
        if not self._script:
            raise AssertionError(
                f"FakeModel script exhausted after {len(self.requests) - 1} responses"
            )
        step = self._script.popleft()
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            return step(req)
        return step


def reply(text: str, *, usage: Usage = DEFAULT_USAGE) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content=(TextBlock(text=text),)),
        usage=usage,
        stop="end_turn",
        model="fake-model",
    )


def call(
    name: str,
    input: dict[str, Any],
    *,
    id: str | None = None,
    text: str = "",
    usage: Usage = DEFAULT_USAGE,
) -> ModelResponse:
    blocks: tuple = (TextBlock(text=text),) if text else ()
    blocks += (ToolCall(id=id or f"call_{next(_ids)}", name=name, input=input),)
    return ModelResponse(
        message=Message(role="assistant", content=blocks),
        usage=usage,
        stop="tool_use",
        model="fake-model",
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/models -q && uv run lint-imports`
Expected: all pass, and the 3 contracts are kept.

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add usta/models tests/models
git commit -m "feat(models): tool-name codec, status mapping, fake adapter, adapter contract"
```

---

### Task 4: Model catalog (caps + prices)

**Files:**
- Create: `config/models.toml`, `usta/models/pricing.py`, `usta/models/caps.py`
- Test: `tests/models/test_catalog.py`

**Interfaces:**
- Produces: `Price(input, output, cache_read, cache_write)` (USD per million tokens), `cost_usd(usage, price) -> float`, `ModelEntry` (`adapter`, caps fields, `price`, and a `.caps -> ModelCaps` property), and `load_catalog(path: Path) -> dict[str, ModelEntry]`, which raises `ConfigError`.

- [ ] **Step 1: Write the failing test** `tests/models/test_catalog.py`:

```python
from pathlib import Path

import pytest

from usta.core.errors import ConfigError
from usta.core.model import Usage
from usta.models.caps import load_catalog
from usta.models.pricing import Price, cost_usd


def test_cost_counts_all_four_token_kinds() -> None:
    price = Price(input=2.0, output=10.0, cache_read=0.2, cache_write=2.5)
    usage = Usage(input_tokens=1_000, output_tokens=500, cache_read_tokens=10_000, cache_write_tokens=2_000)
    assert cost_usd(usage, price) == pytest.approx((2_000 + 5_000 + 2_000 + 5_000) / 1_000_000)


def test_shipped_catalog_has_caps_and_price_for_every_model() -> None:
    catalog = load_catalog(Path("config/models.toml"))
    assert {"claude-sonnet-5-5", "claude-haiku-4-5", "gemini/gemini-2.5-flash", "fake-model"} <= catalog.keys()
    sonnet = catalog["claude-sonnet-5-5"]
    assert sonnet.adapter == "anthropic"
    assert (sonnet.caps.context_tokens, sonnet.caps.max_output_tokens) == (1_000_000, 128_000)
    assert sonnet.price == Price(input=2.0, output=10.0, cache_read=0.2, cache_write=2.5)
    assert catalog["fake-model"].adapter == "fake"


def test_entry_without_price_is_a_config_error(tmp_path: Path) -> None:
    bad = tmp_path / "models.toml"
    bad.write_text(
        '[models."x"]\nadapter = "litellm"\ncontext_tokens = 1\nmax_output_tokens = 1\n'
        'prompt_cache = "none"\nparallel_tool_calls = false\nnative_tools = true\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="'x'"):
        load_catalog(bad)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/models/test_catalog.py -q`
Expected: `ModuleNotFoundError: No module named 'usta.models.caps'`.

- [ ] **Step 3: Implement.** `config/models.toml`:

```toml
# Model catalog: capabilities (ADR-021) + prices in USD per million tokens (P7).
# A profile may only use models listed here; no price entry -> startup refuses.
# Anthropic prices checked 2026-10-08 (first-party API). cache_write = 5-minute TTL (1.25x input).

[models."claude-sonnet-5-5"]
adapter = "anthropic"
context_tokens = 1_000_000
max_output_tokens = 128_000
prompt_cache = "explicit"
parallel_tool_calls = true
native_tools = true
price = { input = 2.00, output = 10.00, cache_read = 0.20, cache_write = 2.50 }

[models."claude-haiku-4-5"]
adapter = "anthropic"
context_tokens = 200_000
max_output_tokens = 64_000
prompt_cache = "explicit"
parallel_tool_calls = true
native_tools = true
price = { input = 1.00, output = 5.00, cache_read = 0.10, cache_write = 1.25 }

# dev-free default (SPEC §20 item 2; re-checked in Task 15). Free tier in dev, but the
# paid list price is kept so cost numbers stay comparable across profiles.
[models."gemini/gemini-2.5-flash"]
adapter = "litellm"
context_tokens = 1_048_576
max_output_tokens = 65_536
prompt_cache = "automatic"
parallel_tool_calls = true
native_tools = true
price = { input = 0.30, output = 2.50, cache_read = 0.03, cache_write = 0.0 }

[models."fake-model"]
adapter = "fake"
context_tokens = 200_000
max_output_tokens = 8_192
prompt_cache = "none"
parallel_tool_calls = true
native_tools = true
price = { input = 0.0, output = 0.0, cache_read = 0.0, cache_write = 0.0 }
```

`usta/models/pricing.py`:

```python
from usta.core.base import Frozen
from usta.core.model import Usage


class Price(Frozen):
    """USD per million tokens."""

    input: float
    output: float
    cache_read: float
    cache_write: float


def cost_usd(usage: Usage, price: Price) -> float:
    return (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_tokens * price.cache_read
        + usage.cache_write_tokens * price.cache_write
    ) / 1_000_000
```

`usta/models/caps.py`:

```python
"""Model catalog loader: caps + price per model id, from config/models.toml."""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from usta.core.errors import ConfigError
from usta.core.model import ModelCaps
from usta.models.pricing import Price


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter: Literal["anthropic", "litellm", "fake"]
    context_tokens: int
    max_output_tokens: int
    prompt_cache: Literal["explicit", "automatic", "none"]
    parallel_tool_calls: bool
    native_tools: bool
    price: Price

    @property
    def caps(self) -> ModelCaps:
        return ModelCaps(
            context_tokens=self.context_tokens,
            max_output_tokens=self.max_output_tokens,
            prompt_cache=self.prompt_cache,
            parallel_tool_calls=self.parallel_tool_calls,
            native_tools=self.native_tools,
        )


def load_catalog(path: Path) -> dict[str, ModelEntry]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    catalog: dict[str, ModelEntry] = {}
    for model_id, raw in data.get("models", {}).items():
        try:
            catalog[model_id] = ModelEntry.model_validate(raw)
        except ValidationError as e:
            raise ConfigError(f"{path}: model {model_id!r}: {e}") from e
    return catalog
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/models/test_catalog.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add config/models.toml usta/models/pricing.py usta/models/caps.py tests/models/test_catalog.py
git commit -m "feat(models): model catalog with caps and prices (P7)"
```

---

### Task 5: Anthropic adapter

**Files:**
- Modify: `pyproject.toml` / `uv.lock` (add `anthropic>=1,<2`)
- Create: `usta/models/anthropic_adapter.py`
- Test: `tests/models/test_anthropic_adapter.py`

**Interfaces:**
- Consumes: `encode`/`decode`, `map_status`, `CONTRACT_REQUEST`, `assert_contract_response`.
- Produces: `AnthropicModel(model_id, caps, *, api_key: str, max_output_tokens: int, effort: str | None = None, http_client=None)`, with `provider = "anthropic"`, which implements `ModelPort`.

Notes for the implementer:
- anthropic 1.x runs on **`httpx2`**, not `httpx`. Test fakes use `httpx2.MockTransport`. An object from the `httpx` package is rejected.
- Pass an explicit `api_key` and refuse an empty one. Otherwise the SDK falls back to `ANTHROPIC_AUTH_TOKEN` or an `ant auth login` profile, which would be a silent credential fallback (P8).
- `max_retries=0`, because retries live in the gateway (Plan Decision 16).
- Sonnet 5.5 always thinks. Its `thinking` blocks come back as `OpaqueBlock`s and must be sent back unchanged.
- Do **not** send `fallbacks` (Plan Decision 6).

- [ ] **Step 1: Add the dependency**

Run: `uv add "anthropic>=1,<2" && uv run python -c "import anthropic, httpx2; print(anthropic.__version__)"`
Expected: a `1.x` version is printed. If resolution fails because no 1.x exists, **stop and report**. Do not fall back to 0.x, because the tests below need httpx2.

- [ ] **Step 2: Write the failing test** `tests/models/test_anthropic_adapter.py`:

```python
import json
from pathlib import Path

import httpx2
import pytest

from usta.core.errors import (
    ConfigError,
    ProviderError,
    ProviderQuotaError,
    ProviderRateLimited,
    TransientProviderError,
)
from usta.core.messages import Message, ToolResult
from usta.models.anthropic_adapter import AnthropicModel
from usta.models.caps import load_catalog
from tests.models.contract import CONTRACT_REQUEST, assert_contract_response

CAPS = load_catalog(Path("config/models.toml"))["claude-sonnet-5-5"].caps

WIRE_RESPONSE = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-5-5",
    "content": [
        {"type": "thinking", "thinking": "", "signature": "sig-abc"},
        {"type": "text", "text": "Oxuyuram."},
        {"type": "tool_use", "id": "toolu_2", "name": "file__read", "input": {"path": "files/qeyd.txt"}},
    ],
    "stop_reason": "tool_use",
    "stop_sequence": None,
    "usage": {
        "input_tokens": 12,
        "output_tokens": 7,
        "cache_creation_input_tokens": 100,
        "cache_read_input_tokens": 900,
    },
}


def make_model(handler, **kw) -> AnthropicModel:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return AnthropicModel(
        "claude-sonnet-5-5", CAPS, api_key="test-key", max_output_tokens=1024, http_client=client, **kw
    )


def capture(seen: dict):
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        return httpx2.Response(200, json=WIRE_RESPONSE)

    return handler


async def test_round_trip_meets_contract_and_wire_shape() -> None:
    seen: dict = {}
    resp = await make_model(capture(seen), effort="medium").complete(CONTRACT_REQUEST)
    assert_contract_response(resp)
    body = seen["body"]
    assert body["model"] == "claude-sonnet-5-5"
    assert body["max_tokens"] == 1024
    assert body["output_config"] == {"effort": "medium"}
    assert "fallbacks" not in body
    assert body["system"] == [
        {"type": "text", "text": "You are Usta.", "cache_control": {"type": "ephemeral"}}
    ]
    assert body["tools"][0]["name"] == "file__read"
    assert body["messages"][1]["content"] == [
        {"type": "tool_use", "id": "toolu_1", "name": "file__read", "input": {"path": "files/a.txt"}}
    ]
    assert body["messages"][2]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "İSTİQAMƏT: Bakı", "is_error": False}
    ]


async def test_thinking_blocks_are_sent_back_unchanged() -> None:
    first = await make_model(capture({})).complete(CONTRACT_REQUEST)
    follow_up = CONTRACT_REQUEST.model_copy(
        update={
            "messages": CONTRACT_REQUEST.messages
            + (first.message, Message(role="user", content=(ToolResult(call_id="toolu_2", content="ok"),)))
        }
    )
    seen: dict = {}
    await make_model(capture(seen)).complete(follow_up)
    echoed = seen["body"]["messages"][3]["content"]
    assert echoed[0] == {"type": "thinking", "thinking": "", "signature": "sig-abc"}
    assert echoed[2]["type"] == "tool_use" and echoed[2]["name"] == "file__read"


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (402, ProviderQuotaError),
        (429, ProviderRateLimited),
        (529, TransientProviderError),
        (500, TransientProviderError),
        (400, ProviderError),
    ],
)
async def test_http_errors_map_to_usta_errors(status: int, error: type) -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={"type": "error", "error": {"type": "x", "message": "boom"}})

    with pytest.raises(ProviderError) as info:
        await make_model(handler).complete(CONTRACT_REQUEST)
    assert type(info.value) is error


async def test_connection_error_is_transient() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down", request=request)

    with pytest.raises(TransientProviderError):
        await make_model(handler).complete(CONTRACT_REQUEST)


def test_empty_api_key_is_refused() -> None:
    with pytest.raises(ConfigError):
        AnthropicModel("claude-sonnet-5-5", CAPS, api_key="", max_output_tokens=1024)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/models/test_anthropic_adapter.py -q`
Expected: `ModuleNotFoundError: No module named 'usta.models.anthropic_adapter'`.

- [ ] **Step 4: Implement** `usta/models/anthropic_adapter.py`:

```python
"""Anthropic adapter: the production path (ADR-020). The only module that imports `anthropic`."""

from __future__ import annotations

from typing import Any

import anthropic

from usta.core.errors import ConfigError, TransientProviderError
from usta.core.messages import Message, OpaqueBlock, TextBlock, ToolCall, ToolResult
from usta.core.model import (
    ModelCaps,
    ModelRequest,
    ModelResponse,
    ModelStop,
    SystemBlock,
    Usage,
)
from usta.models.errors import map_status
from usta.models.toolnames import decode, encode

_STOP: dict[str | None, ModelStop] = {
    "end_turn": "end_turn",
    "stop_sequence": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
}


class AnthropicModel:
    provider = "anthropic"

    def __init__(
        self,
        model_id: str,
        caps: ModelCaps,
        *,
        api_key: str,
        max_output_tokens: int,
        effort: str | None = None,
        http_client: Any = None,
    ) -> None:
        if not api_key:
            raise ConfigError("anthropic adapter needs an explicit API key (no credential fallback)")
        self.model_id = model_id
        self.caps = caps
        self._max_output = max_output_tokens
        self._effort = effort
        # Retries live in the gateway (one policy, every attempt logged), so the SDK's are off.
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, max_retries=0, http_client=http_client
        )

    async def complete(self, req: ModelRequest) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": req.max_output_tokens or self._max_output,
            "system": [_system_block(b) for b in req.system],
            "messages": [_message(m) for m in req.messages],
        }
        if req.tools:
            kwargs["tools"] = [
                {"name": encode(t.name), "description": t.description, "input_schema": t.input_schema}
                for t in req.tools
            ]
        if self._effort:
            kwargs["output_config"] = {"effort": self._effort}
        try:
            msg = await self._client.messages.create(**kwargs)
        except anthropic.APIStatusError as e:
            raise map_status(e.status_code, str(e)) from e
        except anthropic.APIConnectionError as e:  # includes APITimeoutError
            raise TransientProviderError(str(e)) from e
        return _response(msg)


def _system_block(block: SystemBlock) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "text", "text": block.text}
    if block.cache:
        out["cache_control"] = {"type": "ephemeral"}
    return out


def _message(msg: Message) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    for b in msg.content:
        if isinstance(b, TextBlock):
            if b.text:  # the API rejects empty text blocks
                content.append({"type": "text", "text": b.text})
        elif isinstance(b, ToolCall):
            content.append({"type": "tool_use", "id": b.id, "name": encode(b.name), "input": b.input})
        elif isinstance(b, ToolResult):
            content.append(
                {"type": "tool_result", "tool_use_id": b.call_id, "content": b.content, "is_error": b.is_error}
            )
        elif isinstance(b, OpaqueBlock) and b.provider == "anthropic":
            content.append(b.data)
    return {"role": msg.role, "content": content}


def _response(msg: Any) -> ModelResponse:
    blocks: list = []
    for b in msg.content:
        if b.type == "text":
            blocks.append(TextBlock(text=b.text))
        elif b.type == "tool_use":
            blocks.append(ToolCall(id=b.id, name=decode(b.name), input=dict(b.input)))
        else:  # thinking, redacted_thinking, ...: must be echoed back unchanged
            blocks.append(
                OpaqueBlock(provider="anthropic", data=b.model_dump(mode="json", exclude_none=True))
            )
    u = msg.usage
    return ModelResponse(
        message=Message(role="assistant", content=tuple(blocks)),
        usage=Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=u.cache_read_input_tokens or 0,
            cache_write_tokens=u.cache_creation_input_tokens or 0,
        ),
        stop=_STOP.get(msg.stop_reason, "other"),
        model=msg.model,
    )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/models/test_anthropic_adapter.py -q && uv run lint-imports`
Expected: all pass, and the 3 contracts are kept. If the thinking-block echo test fails because `model_dump` adds fields, inspect the dump with `print(b.model_dump(mode="json", exclude_none=True))` and fix the adapter, not the test. The wire must match what the API sent.

- [ ] **Step 6: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add pyproject.toml uv.lock usta/models/anthropic_adapter.py tests/models/test_anthropic_adapter.py
git commit -m "feat(models): anthropic adapter with cache markers, usage and thinking passthrough"
```

---

### Task 6: LiteLLM adapter (exact pin)

**Files:**
- Modify: `pyproject.toml` / `uv.lock` (add `litellm==<exact>`)
- Create: `usta/models/litellm_adapter.py`
- Test: `tests/models/test_litellm_adapter.py`
- Modify: `docs/adr/ADR-020-gateway-and-format.md` (record the pinned version)

**Interfaces:**
- Consumes: `encode`/`decode`, `map_status`, `CONTRACT_REQUEST`, `assert_contract_response`.
- Produces: `LiteLLMModel(model_id, caps, *, api_key: str | None, max_output_tokens: int, api_base: str | None = None, effort: str | None = None, completion=None)`, where `provider = "litellm:<prefix>"` (e.g. `litellm:gemini`). It implements `ModelPort`.

- [ ] **Step 1: Pick and pin the version (F8).**

Run: `uvx pip index versions litellm | head -n 3`. Choose the newest release that is at least 1.83.3. Check https://github.com/BerriAI/litellm/security/advisories for advisories against it, and never use 1.82.7 or 1.82.8. Then run, substituting the chosen version:

```bash
uv add "litellm==1.83.3"
grep -A2 'name = "litellm"' uv.lock    # confirm the exact version and the sha256 hashes are in the lock
```

Append to ADR-020 under Consequences: `Pinned litellm==<version> on 2026-10-DD (hash-locked in uv.lock).`

- [ ] **Step 2: Write the failing test** `tests/models/test_litellm_adapter.py`:

```python
import json
from types import SimpleNamespace
from typing import Any

import pytest

from usta.core.errors import ProviderError, ProviderRateLimited, TransientProviderError
from usta.core.messages import Message, ToolResult
from usta.models.fake import DEFAULT_CAPS
from usta.models.litellm_adapter import LiteLLMModel
from tests.models.contract import CONTRACT_REQUEST, assert_contract_response

WIRE = {
    "id": "x",
    "model": "gemini/gemini-2.5-flash",
    "choices": [
        {
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": "Oxuyuram.",
                "tool_calls": [
                    {
                        "id": "toolu_2",
                        "type": "function",
                        "function": {"name": "file__read", "arguments": '{"path": "files/qeyd.txt"}'},
                    }
                ],
            },
        }
    ],
    "usage": {
        "prompt_tokens": 1012,
        "completion_tokens": 7,
        "prompt_tokens_details": {"cached_tokens": 900},
        "cache_creation_input_tokens": 100,
    },
}


class FakeCompletion:
    def __init__(self, wire: dict | None = None, error: Exception | None = None) -> None:
        self.wire, self.error, self.kwargs = wire, error, {}

    async def __call__(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(model_dump=lambda: self.wire)


def make(fake: FakeCompletion, **kw: Any) -> LiteLLMModel:
    return LiteLLMModel(
        "gemini/gemini-2.5-flash", DEFAULT_CAPS, api_key="k-1", max_output_tokens=512, completion=fake, **kw
    )


def with_tool_call(arguments: str, finish: str = "tool_calls") -> dict:
    wire = json.loads(json.dumps(WIRE))
    wire["choices"][0]["finish_reason"] = finish
    wire["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = arguments
    return wire


async def test_round_trip_meets_contract_and_wire_shape() -> None:
    fake = FakeCompletion(WIRE)
    model = make(fake)
    assert model.provider == "litellm:gemini"
    assert_contract_response(await model.complete(CONTRACT_REQUEST))
    kw = fake.kwargs
    assert kw["model"] == "gemini/gemini-2.5-flash"
    assert kw["api_key"] == "k-1"
    assert kw["max_tokens"] == 512
    assert kw["messages"][0] == {
        "role": "system",
        "content": [{"type": "text", "text": "You are Usta.", "cache_control": {"type": "ephemeral"}}],
    }
    assert kw["messages"][2]["tool_calls"][0]["function"] == {
        "name": "file__read",
        "arguments": '{"path": "files/a.txt"}',
    }
    assert kw["messages"][3] == {"role": "tool", "tool_call_id": "toolu_1", "content": "İSTİQAMƏT: Bakı"}
    assert kw["tools"][0]["function"]["name"] == "file__read"


async def test_error_tool_results_are_marked_in_content() -> None:
    fake = FakeCompletion(WIRE)
    req = CONTRACT_REQUEST.model_copy(
        update={"messages": (Message(role="user", content=(ToolResult(call_id="c", content="no", is_error=True),)),)}
    )
    await make(fake).complete(req)
    assert fake.kwargs["messages"][-1]["content"] == "ERROR: no"


async def test_invalid_json_arguments_become_input_error() -> None:
    resp = await make(FakeCompletion(with_tool_call('{"path": "files/'))).complete(CONTRACT_REQUEST)
    [call] = resp.tool_calls()
    assert call.input == {} and "not valid JSON" in (call.input_error or "")


async def test_tool_calls_win_over_a_stop_finish_reason() -> None:
    resp = await make(FakeCompletion(with_tool_call('{"path": "x"}', finish="stop"))).complete(CONTRACT_REQUEST)
    assert resp.stop == "tool_use"


async def test_length_finish_reason_is_max_tokens_even_with_tool_calls() -> None:
    resp = await make(FakeCompletion(with_tool_call('{"pa', finish="length"))).complete(CONTRACT_REQUEST)
    assert resp.stop == "max_tokens"


class ProviderBoom(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"status {status}")
        self.status_code = status
        self.llm_provider = "gemini"


@pytest.mark.parametrize(
    ("status", "error"),
    [(429, ProviderRateLimited), (503, TransientProviderError), (400, ProviderError)],
)
async def test_provider_errors_are_mapped(status: int, error: type) -> None:
    with pytest.raises(ProviderError) as info:
        await make(FakeCompletion(error=ProviderBoom(status))).complete(CONTRACT_REQUEST)
    assert type(info.value) is error


async def test_our_own_bugs_are_not_disguised_as_provider_errors() -> None:
    with pytest.raises(TypeError):
        await make(FakeCompletion(error=TypeError("bug"))).complete(CONTRACT_REQUEST)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/models/test_litellm_adapter.py -q`
Expected: `ModuleNotFoundError: No module named 'usta.models.litellm_adapter'`.

- [ ] **Step 4: Implement** `usta/models/litellm_adapter.py`:

```python
"""LiteLLM adapter, library mode: free tiers, local servers, other providers (ADR-020).

The ONLY module that imports litellm (import-linter, F8). It receives only its own key.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")  # no network fetch on import

import litellm  # noqa: E402

from usta.core.messages import Message, TextBlock, ToolCall  # noqa: E402
from usta.core.model import (  # noqa: E402
    ModelCaps,
    ModelRequest,
    ModelResponse,
    ModelStop,
    SystemBlock,
    Usage,
)
from usta.models.errors import map_status  # noqa: E402
from usta.models.toolnames import decode, encode  # noqa: E402

Completion = Callable[..., Awaitable[Any]]
_STOP: dict[str | None, ModelStop] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "content_filter": "refusal",
}


class LiteLLMModel:
    def __init__(
        self,
        model_id: str,
        caps: ModelCaps,
        *,
        api_key: str | None,
        max_output_tokens: int,
        api_base: str | None = None,
        effort: str | None = None,
        completion: Completion | None = None,
    ) -> None:
        self.model_id = model_id
        self.caps = caps
        self.provider = "litellm:" + model_id.split("/", 1)[0]
        self._api_key = api_key
        self._api_base = api_base
        self._max_output = max_output_tokens
        self._effort = effort
        self._completion = completion or litellm.acompletion

    async def complete(self, req: ModelRequest) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "messages": _messages(req),
            "max_tokens": req.max_output_tokens or self._max_output,
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_base:
            kwargs["api_base"] = self._api_base
        if self._effort:
            kwargs["reasoning_effort"] = self._effort
        if req.tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": encode(t.name),
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in req.tools
            ]
        try:
            raw = await self._completion(**kwargs)
        except Exception as e:
            status = getattr(e, "status_code", None)
            if status is None and getattr(e, "llm_provider", None) is None:
                raise  # our bug, not the provider's: never disguise it
            raise map_status(status, str(e)) from e
        return _response(raw.model_dump() if hasattr(raw, "model_dump") else raw, self.model_id)


def _system_part(block: SystemBlock) -> dict[str, Any]:
    part: dict[str, Any] = {"type": "text", "text": block.text}
    if block.cache:
        part["cache_control"] = {"type": "ephemeral"}
    return part


def _messages(req: ModelRequest) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if req.system:
        out.append({"role": "system", "content": [_system_part(b) for b in req.system]})
    for m in req.messages:
        if m.role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.text() or None}
            calls = m.tool_calls()
            if calls:
                msg["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": encode(c.name),
                            "arguments": json.dumps(c.input, ensure_ascii=False),
                        },
                    }
                    for c in calls
                ]
            out.append(msg)
        else:
            for r in m.tool_results():
                content = f"ERROR: {r.content}" if r.is_error else r.content
                out.append({"role": "tool", "tool_call_id": r.call_id, "content": content})
            if text := m.text():
                out.append({"role": "user", "content": text})
    return out


def _parse_args(raw: Any) -> tuple[dict[str, Any], str | None]:
    if isinstance(raw, dict):
        return raw, None
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError as e:
        return {}, f"arguments are not valid JSON ({e.msg})"
    if not isinstance(parsed, dict):
        return {}, "arguments must be a JSON object"
    return parsed, None


def _response(d: dict[str, Any], model_id: str) -> ModelResponse:
    choice = d["choices"][0]
    msg = choice.get("message") or {}
    blocks: list = []
    if msg.get("content"):
        blocks.append(TextBlock(text=msg["content"]))
    for tc in msg.get("tool_calls") or []:
        fn = tc["function"]
        args, err = _parse_args(fn.get("arguments"))
        blocks.append(ToolCall(id=tc["id"], name=decode(fn["name"]), input=args, input_error=err))
    finish = choice.get("finish_reason")
    if finish == "length":
        stop: ModelStop = "max_tokens"
    elif any(isinstance(b, ToolCall) for b in blocks):
        stop = "tool_use"
    else:
        stop = _STOP.get(finish, "other")
    u = d.get("usage") or {}
    cache_read = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or u.get(
        "cache_read_input_tokens"
    ) or 0
    cache_write = u.get("cache_creation_input_tokens") or 0
    usage = Usage(
        input_tokens=max(0, (u.get("prompt_tokens") or 0) - cache_read - cache_write),
        output_tokens=u.get("completion_tokens") or 0,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )
    return ModelResponse(
        message=Message(role="assistant", content=tuple(blocks)),
        usage=usage,
        stop=stop,
        model=d.get("model") or model_id,
    )
```

Known limitation: provider-specific fields such as Gemini thought signatures are not preserved yet. The live round-trip test in Task 15 catches this if the chosen model needs them.

- [ ] **Step 5: Run the tests and the contracts**

Run: `uv run pytest tests/models -q && uv run lint-imports`
Expected: all pass. The LiteLLM contract is kept: only `usta.models.litellm_adapter` imports `litellm`.

- [ ] **Step 6: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add pyproject.toml uv.lock usta/models/litellm_adapter.py tests/models/test_litellm_adapter.py docs/adr/ADR-020-gateway-and-format.md
git commit -m "feat(models): litellm adapter, exact hash-locked pin (F8)"
```

---

### Task 7: Gateway (logging, retries, timeouts, circuit breaker, cost)

**Files:**
- Create: `usta/models/gateway.py`
- Test: `tests/models/test_gateway.py`

**Interfaces:**
- Consumes: `ModelPort`, `AuditSink`, `Price`, `cost_usd`, `ModelCallRecord`, and the provider errors.
- Produces:
  - `Gateway(models: Mapping[Role, ModelPort], prices: Mapping[str, Price], audit: AuditSink, *, max_attempts=3, base_delay_s=1.0, timeout_s=180.0, breaker_threshold=5, breaker_reset_s=60.0, sleep=asyncio.sleep, clock=time.monotonic)`, which implements `ModelGateway`.
  - `complete(req)` returns a `ModelResponse` with `cost_usd` filled in.
  - A missing price raises `ConfigError` at construction (P7).
  - A persistent 429 becomes `ProviderQuotaError`.
  - An open circuit raises `ProviderUnavailable`.
  - Every attempt writes one `ModelCallRecord`, including failed attempts.

- [ ] **Step 1: Write the failing test** `tests/models/test_gateway.py`:

```python
import asyncio

import pytest

from usta.core.errors import (
    ConfigError,
    ProviderQuotaError,
    ProviderRateLimited,
    ProviderUnavailable,
    TransientProviderError,
)
from usta.core.messages import Message
from usta.core.model import ModelRequest, SystemBlock, Usage
from usta.models.fake import DEFAULT_CAPS, FakeModel, reply
from usta.models.gateway import Gateway
from usta.models.pricing import Price
from tests.fakes import FakeClock, InMemoryStore

PRICE = Price(input=2.0, output=10.0, cache_read=0.2, cache_write=2.5)


def request(role: str = "main") -> ModelRequest:
    return ModelRequest(
        role=role,
        system=(SystemBlock(text="sys", cache=True),),
        messages=(Message.user_text("salam"),),
        prompt_version="p1",
        run_id="r1",
        user_id="u1",
    )


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def make(script, **kw):
    store, sleeps, model = InMemoryStore(), Sleeps(), FakeModel(script)
    gw = Gateway({"main": model}, {"fake-model": PRICE}, audit=store, sleep=sleeps, **kw)
    return gw, model, store, sleeps


async def test_success_prices_the_call_and_logs_it() -> None:
    gw, _, store, _ = make([reply("ok", usage=Usage(input_tokens=1000, output_tokens=100))])
    resp = await gw.complete(request())
    assert resp.cost_usd == pytest.approx((1000 * 2 + 100 * 10) / 1_000_000)
    [rec] = store.model_calls
    assert (rec.run_id, rec.user_id, rec.role, rec.model, rec.prompt_version, rec.attempt) == (
        "r1", "u1", "main", "fake-model", "p1", 1,
    )
    assert rec.cost_usd == resp.cost_usd and rec.error is None and rec.response is not None
    assert rec.request["messages"][0]["content"][0]["text"] == "salam"


async def test_transient_error_is_retried_with_backoff() -> None:
    gw, _, store, sleeps = make([TransientProviderError("503"), reply("ok")])
    assert (await gw.complete(request())).message.text() == "ok"
    assert sleeps.calls == [1.0]
    assert [r.error is None for r in store.model_calls] == [False, True]
    assert [r.attempt for r in store.model_calls] == [1, 2]


async def test_gives_up_after_max_attempts() -> None:
    gw, _, store, sleeps = make([TransientProviderError(x) for x in "abc"])
    with pytest.raises(TransientProviderError, match="c"):
        await gw.complete(request())
    assert sleeps.calls == [1.0, 2.0]
    assert len(store.model_calls) == 3


async def test_persistent_rate_limit_becomes_provider_quota() -> None:
    gw, *_ = make([ProviderRateLimited("429")] * 3)
    with pytest.raises(ProviderQuotaError):
        await gw.complete(request())


async def test_non_retryable_error_is_logged_and_raised_at_once() -> None:
    gw, _, store, sleeps = make([ProviderQuotaError("billing")])
    with pytest.raises(ProviderQuotaError):
        await gw.complete(request())
    assert sleeps.calls == []
    assert "billing" in (store.model_calls[0].error or "")


async def test_unexpected_exception_is_logged_then_raised() -> None:
    gw, _, store, _ = make([RuntimeError("bug")])
    with pytest.raises(RuntimeError):
        await gw.complete(request())
    assert store.model_calls[0].error == "RuntimeError: bug"


async def test_timeout_counts_as_transient() -> None:
    class Hanging:
        provider, model_id, caps = "hang", "fake-model", DEFAULT_CAPS

        async def complete(self, req: ModelRequest):
            await asyncio.sleep(10)

    store = InMemoryStore()
    gw = Gateway({"main": Hanging()}, {"fake-model": PRICE}, audit=store, sleep=Sleeps(), timeout_s=0.01)
    with pytest.raises(TransientProviderError, match="no response within"):
        await gw.complete(request())
    assert len(store.model_calls) == 3


async def test_circuit_opens_after_consecutive_failures_and_recovers() -> None:
    clock = FakeClock()
    gw, model, _, _ = make(
        [TransientProviderError("x"), TransientProviderError("y"), reply("back")],
        max_attempts=1, breaker_threshold=2, breaker_reset_s=60, clock=clock,
    )
    for _ in range(2):
        with pytest.raises(TransientProviderError):
            await gw.complete(request())
    with pytest.raises(ProviderUnavailable):
        await gw.complete(request())
    assert len(model.requests) == 2  # the open circuit did not call the provider
    clock.now += 61
    assert (await gw.complete(request())).message.text() == "back"


def test_missing_price_refuses_construction() -> None:
    with pytest.raises(ConfigError, match="P7"):
        Gateway({"main": FakeModel()}, {}, audit=InMemoryStore())


async def test_routes_by_role() -> None:
    main = FakeModel([reply("main")], model_id="m")
    light = FakeModel([reply("light")], model_id="l")
    gw = Gateway({"main": main, "light": light}, {"m": PRICE, "l": PRICE}, audit=InMemoryStore())
    assert (await gw.complete(request("light"))).message.text() == "light"
    assert main.requests == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/models/test_gateway.py -q`
Expected: `ModuleNotFoundError: No module named 'usta.models.gateway'`.

- [ ] **Step 3: Implement** `usta/models/gateway.py`:

```python
"""Gateway: logging, retries, timeouts, circuit breaker and cost, outside the adapters
(ADR-020, P7). Every attempt is written to the audit sink, including failures."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping

from usta.core.audit import ModelCallRecord
from usta.core.errors import (
    ConfigError,
    ProviderQuotaError,
    ProviderRateLimited,
    ProviderUnavailable,
    TransientProviderError,
)
from usta.core.model import ModelRequest, ModelResponse, Role, Usage
from usta.models.pricing import Price, cost_usd
from usta.ports import AuditSink, ModelPort

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


class CircuitBreaker:
    def __init__(self, threshold: int, reset_after_s: float, clock: Clock) -> None:
        self._threshold = threshold
        self._reset_after = reset_after_s
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    def check(self, provider: str) -> None:
        if self._opened_at is None:
            return
        if self._clock() - self._opened_at >= self._reset_after:
            self._opened_at = None
            self._failures = self._threshold - 1  # half-open: one more failure re-opens
            return
        raise ProviderUnavailable(
            f"{provider}: circuit open after {self._threshold} consecutive failures"
        )

    def success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = self._clock()


class Gateway:
    def __init__(
        self,
        models: Mapping[Role, ModelPort],
        prices: Mapping[str, Price],
        audit: AuditSink,
        *,
        max_attempts: int = 3,
        base_delay_s: float = 1.0,
        timeout_s: float = 180.0,
        breaker_threshold: int = 5,
        breaker_reset_s: float = 60.0,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.monotonic,
    ) -> None:
        missing = sorted({m.model_id for m in models.values()} - prices.keys())
        if missing:
            raise ConfigError(f"P7: no price entry for {missing}")
        self._models = dict(models)
        self._prices = dict(prices)
        self._audit = audit
        self._max_attempts = max_attempts
        self._base_delay_s = base_delay_s
        self._timeout_s = timeout_s
        self._breaker_threshold = breaker_threshold
        self._breaker_reset_s = breaker_reset_s
        self._sleep = sleep
        self._clock = clock
        self._breakers: dict[str, CircuitBreaker] = {}

    async def complete(self, req: ModelRequest) -> ModelResponse:
        model = self._models[req.role]
        breaker = self._breakers.setdefault(
            model.provider,
            CircuitBreaker(self._breaker_threshold, self._breaker_reset_s, self._clock),
        )
        breaker.check(model.provider)
        last: TransientProviderError | None = None
        for attempt in range(1, self._max_attempts + 1):
            started = self._clock()
            try:
                resp = await asyncio.wait_for(model.complete(req), self._timeout_s)
            except TimeoutError:
                last = TransientProviderError(
                    f"{model.model_id}: no response within {self._timeout_s}s"
                )
            except TransientProviderError as e:
                last = e
            except Exception as e:  # ProviderError or a bug: log, then raise unchanged
                await self._log(req, model, attempt, started, error=e)
                raise
            else:
                cost = cost_usd(resp.usage, self._prices[model.model_id])
                resp = resp.model_copy(update={"cost_usd": cost})
                await self._log(req, model, attempt, started, resp=resp)
                breaker.success()
                return resp
            await self._log(req, model, attempt, started, error=last)
            breaker.failure()
            if attempt < self._max_attempts:
                await self._sleep(self._base_delay_s * 2 ** (attempt - 1))
        assert last is not None
        if isinstance(last, ProviderRateLimited):
            raise ProviderQuotaError(
                f"{model.model_id}: still rate limited after {self._max_attempts} attempts"
            ) from last
        raise last

    async def _log(
        self,
        req: ModelRequest,
        model: ModelPort,
        attempt: int,
        started: float,
        *,
        resp: ModelResponse | None = None,
        error: BaseException | None = None,
    ) -> None:
        await self._audit.model_call(
            ModelCallRecord(
                run_id=req.run_id,
                user_id=req.user_id,
                role=req.role,
                provider=model.provider,
                model=model.model_id,
                prompt_version=req.prompt_version,
                attempt=attempt,
                request=req.model_dump(mode="json"),
                response=resp.model_dump(mode="json") if resp else None,
                error=f"{type(error).__name__}: {error}" if error else None,
                usage=resp.usage if resp else Usage(),
                cost_usd=resp.cost_usd if resp else 0.0,
                latency_ms=int((self._clock() - started) * 1000),
            )
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/models/test_gateway.py -q && uv run lint-imports`
Expected: `10 passed`, and the contracts are kept.

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add usta/models/gateway.py tests/models/test_gateway.py
git commit -m "feat(models): gateway with per-attempt audit, retries, timeout, breaker, cost"
```

---

### Task 8: Tool registry, pipeline, `file.read`, `todo`

**Files:**
- Create: `usta/tools/registry.py`, `usta/tools/pipeline.py`, `usta/tools/builtin/files.py`, `usta/tools/builtin/todo.py`
- Modify: `usta/tools/builtin/__init__.py`, `tests/fakes.py` (append `ECHO`, `FAKE_PRICE`, `make_context`)
- Test: `tests/tools/__init__.py`, `tests/tools/test_pipeline.py`, `tests/tools/test_files.py`, `tests/tools/test_todo.py`

**Interfaces:**
- Consumes: `ToolSpec`, `ToolCall`, `ToolResult`, `ToolOutcome`, `ToolCallRecord`, `Event`, `RunState`, `TodoItem`, `ToolInputError`, `AuditSink`, `Gateway` (only inside `tests/fakes.make_context`).
- Produces:
  - `ToolOutput(content, is_error=False, event=None)`, `ToolContext(run, files_dir, out_dir)`, `Tool(name, description, input_schema, tier, fn)` with `.spec()`, `ToolRegistry(tools=())` with `.register`, `.get`, `.names()`, `.specs()` (sorted by name)
  - `ToolPipeline(registry, audit, workspace_root: Path, clock=time.monotonic)`, which implements `ToolPipelinePort`. The workspace layout is `<root>/<user_id>/files/` and `<root>/<user_id>/runs/<run_id>/out/`.
  - `FILE_READ` (tier `read`), `TODO` (tier `local`), `builtin_tools() -> list[Tool]`
  - `tests.fakes.ECHO` (tool `test.echo`), `FAKE_PRICE` (10 input + 5 output tokens = $0.30), `make_context(script, store, workspace_root, *, tools=(ECHO,), price=FAKE_PRICE) -> tuple[RunContext, FakeModel]`

- [ ] **Step 1: Write the failing tests.** Create an empty `tests/tools/__init__.py`. Then `tests/tools/test_pipeline.py`:

```python
from pathlib import Path

import pytest

from usta.core.messages import ToolCall, ToolResult
from usta.core.run import RunState
from usta.tools.pipeline import ToolPipeline
from usta.tools.registry import Tool, ToolOutput, ToolRegistry
from tests.fakes import ECHO, InMemoryStore


def run_state() -> RunState:
    return RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)


def pipeline(tmp_path: Path, *tools: Tool) -> tuple[ToolPipeline, InMemoryStore]:
    store = InMemoryStore()
    return ToolPipeline(ToolRegistry(tools or (ECHO,)), audit=store, workspace_root=tmp_path), store


async def test_valid_call_is_executed_and_audited_intent_then_done(tmp_path: Path) -> None:
    p, store = pipeline(tmp_path)
    out = await p.handle(ToolCall(id="c1", name="test.echo", input={"text": "salam"}), run_state())
    assert out.result == ToolResult(call_id="c1", content="echo: salam")
    assert [r.phase for r in store.tool_calls] == ["intent", "done"]
    done = store.tool_calls[1]
    assert (done.output, done.is_error, done.run_id, done.user_id) == ("echo: salam", False, "r1", "u1")


async def test_unknown_tool_returns_error_listing_real_tools(tmp_path: Path) -> None:
    p, store = pipeline(tmp_path)
    out = await p.handle(ToolCall(id="c1", name="fleet.delete_all", input={}), run_state())
    assert out.result.is_error
    assert "unknown tool 'fleet.delete_all'" in out.result.content and "test.echo" in out.result.content
    assert [r.phase for r in store.tool_calls] == ["done"]


async def test_unparsable_arguments_are_reported(tmp_path: Path) -> None:
    p, _ = pipeline(tmp_path)
    call = ToolCall(id="c1", name="test.echo", input={}, input_error="arguments are not valid JSON")
    out = await p.handle(call, run_state())
    assert out.result.is_error and "not valid JSON" in out.result.content


async def test_schema_violations_are_reported(tmp_path: Path) -> None:
    p, store = pipeline(tmp_path)
    out = await p.handle(ToolCall(id="c1", name="test.echo", input={"txt": 1}), run_state())
    assert out.result.is_error
    assert "'text' is a required property" in out.result.content
    assert [r.phase for r in store.tool_calls] == ["done"]  # never executed


async def test_tool_exception_becomes_error_result(tmp_path: Path) -> None:
    async def boom(args, ctx) -> ToolOutput:
        raise RuntimeError("disk on fire")

    tool = Tool(name="test.boom", description="x", input_schema={"type": "object"}, tier="local", fn=boom)
    p, store = pipeline(tmp_path, tool)
    out = await p.handle(ToolCall(id="c1", name="test.boom", input={}), run_state())
    assert out.result.is_error and "RuntimeError: disk on fire" in out.result.content
    assert [r.phase for r in store.tool_calls] == ["intent", "done"]


def test_registry_rejects_bad_names_and_duplicates() -> None:
    reg = ToolRegistry([ECHO])
    with pytest.raises(ValueError, match="duplicate"):
        reg.register(ECHO)
    for bad in ["File.read", "file__read", "file..read", ""]:
        with pytest.raises(ValueError, match="invalid tool name"):
            reg.register(Tool(name=bad, description="x", input_schema={"type": "object"}, tier="local", fn=ECHO.fn))


def test_specs_are_sorted_for_a_stable_cached_prefix() -> None:
    zeta = Tool(name="zeta", description="z", input_schema={"type": "object"}, tier="local", fn=ECHO.fn)
    alpha = Tool(name="alpha", description="a", input_schema={"type": "object"}, tier="local", fn=ECHO.fn)
    assert [s.name for s in ToolRegistry([zeta, alpha]).specs()] == ["alpha", "zeta"]
```

`tests/tools/test_files.py`:

```python
import os
from pathlib import Path

import pytest

from usta.core.errors import ToolInputError
from usta.core.run import RunState
from usta.tools.builtin.files import FILE_READ, MAX_CHARS
from usta.tools.registry import ToolContext


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    files = tmp_path / "u1" / "files"
    out = tmp_path / "u1" / "runs" / "r1" / "out"
    files.mkdir(parents=True)
    out.mkdir(parents=True)
    run = RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    return ToolContext(run=run, files_dir=files, out_dir=out)


async def test_reads_workspace_and_output_files_as_utf8(ctx: ToolContext) -> None:
    (ctx.files_dir / "qeyd.txt").write_text("İSTİQAMƏT: Gəncə\n", encoding="utf-8")
    (ctx.out_dir / "hesabat.md").write_text("# Hesabat", encoding="utf-8")
    assert (await FILE_READ.fn({"path": "files/qeyd.txt"}, ctx)).content == "İSTİQAMƏT: Gəncə\n"
    assert (await FILE_READ.fn({"path": "out/hesabat.md"}, ctx)).content == "# Hesabat"


@pytest.mark.parametrize(
    "path",
    ["files/../../../etc/passwd", "/etc/passwd", "etc/passwd", "runs/r1/out/x", "files/../../u2/files/x"],
)
async def test_paths_outside_the_workspace_are_refused(ctx: ToolContext, path: str) -> None:
    with pytest.raises(ToolInputError):
        await FILE_READ.fn({"path": path}, ctx)


async def test_symlink_escape_is_refused(ctx: ToolContext, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("token", encoding="utf-8")
    os.symlink(secret, ctx.files_dir / "link.txt")
    with pytest.raises(ToolInputError, match="escapes"):
        await FILE_READ.fn({"path": "files/link.txt"}, ctx)


async def test_missing_file_and_directory_are_clear_errors(ctx: ToolContext) -> None:
    with pytest.raises(ToolInputError, match="not a file"):
        await FILE_READ.fn({"path": "files/yoxdur.txt"}, ctx)
    with pytest.raises(ToolInputError, match="not a file"):
        await FILE_READ.fn({"path": "files"}, ctx)


async def test_large_files_are_truncated_with_a_marker(ctx: ToolContext) -> None:
    (ctx.files_dir / "big.txt").write_text("ə" * (MAX_CHARS + 10), encoding="utf-8")
    out = (await FILE_READ.fn({"path": "files/big.txt"}, ctx)).content
    assert out.startswith("ə" * MAX_CHARS)
    assert out.endswith(f"[truncated: showing {MAX_CHARS} of {MAX_CHARS + 10} characters]")
```

`tests/tools/test_todo.py`:

```python
from pathlib import Path

from usta.core.messages import ToolCall
from usta.core.run import RunState, TodoItem
from usta.tools.builtin import builtin_tools
from usta.tools.pipeline import ToolPipeline
from usta.tools.registry import ToolRegistry
from tests.fakes import InMemoryStore


async def test_todo_replaces_the_list_and_emits_an_event(tmp_path: Path) -> None:
    run = RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    p = ToolPipeline(ToolRegistry(builtin_tools()), audit=InMemoryStore(), workspace_root=tmp_path)
    items = [{"content": "Hesabatı yoxla", "status": "in_progress"}, {"content": "Zəng et", "status": "pending"}]
    out = await p.handle(ToolCall(id="c1", name="todo", input={"items": items}), run)
    assert not out.result.is_error
    assert run.todo == [TodoItem(**i) for i in items]
    assert "[in_progress] Hesabatı yoxla" in out.result.content
    assert out.event is not None and out.event.type == "todo_updated"
    assert out.event.data == {"items": items}


async def test_todo_rejects_unknown_status(tmp_path: Path) -> None:
    run = RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    p = ToolPipeline(ToolRegistry(builtin_tools()), audit=InMemoryStore(), workspace_root=tmp_path)
    bad = {"items": [{"content": "x", "status": "maybe"}]}
    out = await p.handle(ToolCall(id="c1", name="todo", input=bad), run)
    assert out.result.is_error and run.todo == []


def test_builtin_tools_are_file_read_and_todo() -> None:
    assert sorted(t.name for t in builtin_tools()) == ["file.read", "todo"]
```

Append to `tests/fakes.py` (add the imports at the top of the file):

```python
from pathlib import Path

from usta.models.fake import FakeModel, ScriptStep
from usta.models.gateway import Gateway
from usta.models.pricing import Price
from usta.ports import RunContext
from usta.tools.pipeline import ToolPipeline
from usta.tools.registry import Tool, ToolContext, ToolOutput, ToolRegistry


async def _echo(args: dict, ctx: ToolContext) -> ToolOutput:
    return ToolOutput(f"echo: {args['text']}")


ECHO = Tool(
    name="test.echo",
    description="Echo text back.",
    input_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    },
    tier="local",
    fn=_echo,
)

# 10 input + 5 output tokens (the fake's default usage) cost $0.20 + $0.10 = $0.30.
FAKE_PRICE = Price(input=20_000, output=20_000, cache_read=0, cache_write=0)


async def _no_sleep(_seconds: float) -> None:
    return None


def make_context(
    script: list[ScriptStep],
    store: InMemoryStore,
    workspace_root: Path,
    *,
    tools: tuple[Tool, ...] = (ECHO,),
    price: Price = FAKE_PRICE,
) -> tuple[RunContext, FakeModel]:
    model = FakeModel(script)
    gateway = Gateway({"main": model}, {model.model_id: price}, audit=store, sleep=_no_sleep)
    pipeline = ToolPipeline(ToolRegistry(tools), audit=store, workspace_root=workspace_root)
    return RunContext(models=gateway, tools=pipeline, store=store), model
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/tools -q`
Expected: `ModuleNotFoundError: No module named 'usta.tools.registry'`.

- [ ] **Step 3: Implement.** `usta/tools/registry.py`:

```python
"""Tool registry. Tool names are dotted lowercase; '__' is reserved for wire encoding."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator

from usta.core.events import Event
from usta.core.model import ToolSpec
from usta.core.run import RunState

Tier = Literal["read", "local", "egress", "external_write"]
_NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")


@dataclass(frozen=True)
class ToolOutput:
    content: str
    is_error: bool = False
    event: Event | None = None


@dataclass(frozen=True)
class ToolContext:
    run: RunState
    files_dir: Path  # workspaces/{user}/files (read-only for the agent)
    out_dir: Path  # workspaces/{user}/runs/{run_id}/out


ToolFn = Callable[[dict[str, Any], ToolContext], Awaitable[ToolOutput]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    tier: Tier
    fn: ToolFn

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, input_schema=self.input_schema)


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if not _NAME.match(tool.name) or "__" in tool.name:
            raise ValueError(f"invalid tool name {tool.name!r}")
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool {tool.name!r}")
        Draft202012Validator.check_schema(tool.input_schema)
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> tuple[ToolSpec, ...]:
        """Sorted by name so the cached prompt prefix stays byte-stable (R10)."""
        return tuple(self._tools[n].spec() for n in self.names())
```

`usta/tools/pipeline.py`:

```python
"""Tool pipeline shared by both engines (SPEC §7):
registry -> JSON-schema validation -> audit(intent) -> execute -> audit(done).
M2 inserts verdict + taint after validation; M3 inserts layer-1 offload after execute."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from usta.core.audit import ToolCallRecord
from usta.core.errors import ToolInputError
from usta.core.messages import ToolCall, ToolResult
from usta.core.model import ToolSpec
from usta.core.run import RunState
from usta.core.tools import ToolOutcome
from usta.ports import AuditSink
from usta.tools.registry import ToolContext, ToolOutput, ToolRegistry

log = logging.getLogger(__name__)


class ToolPipeline:
    def __init__(
        self,
        registry: ToolRegistry,
        audit: AuditSink,
        workspace_root: Path,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._registry = registry
        self._audit = audit
        self._root = workspace_root
        self._clock = clock

    def specs(self) -> tuple[ToolSpec, ...]:
        return self._registry.specs()

    async def handle(self, call: ToolCall, run: RunState) -> ToolOutcome:
        tool = self._registry.get(call.name)
        if tool is None:
            available = ", ".join(self._registry.names())
            return await self._reject(call, run, f"unknown tool {call.name!r}; available: {available}")
        if call.input_error:
            return await self._reject(call, run, f"invalid arguments for {call.name}: {call.input_error}")
        errors = sorted(
            Draft202012Validator(tool.input_schema).iter_errors(call.input),
            key=lambda e: list(e.absolute_path),
        )
        if errors:
            detail = "; ".join(_format(e) for e in errors)
            return await self._reject(call, run, f"invalid arguments for {call.name}: {detail}")

        await self._audit.tool_call(self._record(call, run, "intent"))
        started = self._clock()
        try:
            out = await tool.fn(call.input, self._context(run))
        except ToolInputError as e:
            out = ToolOutput(str(e), is_error=True)
        except Exception as e:  # reported to the model, logged, audited; never swallowed silently
            log.exception("tool %s failed in run %s", call.name, run.id)
            out = ToolOutput(f"{call.name} failed: {type(e).__name__}: {e}", is_error=True)
        latency_ms = int((self._clock() - started) * 1000)
        await self._audit.tool_call(
            self._record(call, run, "done", out.content, out.is_error, latency_ms)
        )
        return ToolOutcome(
            result=ToolResult(call_id=call.id, content=out.content, is_error=out.is_error),
            event=out.event,
        )

    def _context(self, run: RunState) -> ToolContext:
        user_dir = self._root / run.user_id
        return ToolContext(
            run=run, files_dir=user_dir / "files", out_dir=user_dir / "runs" / run.id / "out"
        )

    async def _reject(self, call: ToolCall, run: RunState, message: str) -> ToolOutcome:
        await self._audit.tool_call(self._record(call, run, "done", message, True, 0))
        return ToolOutcome(result=ToolResult(call_id=call.id, content=message, is_error=True))

    @staticmethod
    def _record(
        call: ToolCall,
        run: RunState,
        phase: str,
        output: str | None = None,
        is_error: bool | None = None,
        latency_ms: int | None = None,
    ) -> ToolCallRecord:
        return ToolCallRecord(
            run_id=run.id,
            user_id=run.user_id,
            call_id=call.id,
            tool=call.name,
            phase=phase,
            input=call.input,
            output=output,
            is_error=is_error,
            latency_ms=latency_ms,
        )


def _format(error: ValidationError) -> str:
    where = "/".join(str(p) for p in error.absolute_path) or "(root)"
    return f"{where}: {error.message}"
```

`usta/tools/builtin/files.py`:

```python
"""file.read (M0). file.list, file.search and file.write arrive in M1."""

from __future__ import annotations

import asyncio
from pathlib import Path, PurePosixPath
from typing import Any

from usta.core.errors import ToolInputError
from usta.tools.registry import Tool, ToolContext, ToolOutput

MAX_CHARS = 50_000  # until layer-1 offload (M3) stores large results as files


def resolve(path: str, ctx: ToolContext) -> Path:
    """Map 'files/...' or 'out/...' to a real path inside the user's workspace; refuse escapes."""
    rel = PurePosixPath(path)
    roots = {"files": ctx.files_dir, "out": ctx.out_dir}
    if rel.is_absolute() or not rel.parts or rel.parts[0] not in roots:
        raise ToolInputError(f"path must start with files/ or out/: {path!r}")
    root = roots[rel.parts[0]].resolve()
    target = root.joinpath(*rel.parts[1:]).resolve()  # resolves symlinks
    if not target.is_relative_to(root):
        raise ToolInputError(f"path escapes the workspace: {path!r}")
    return target


async def _read(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
    target = resolve(args["path"], ctx)
    if not target.is_file():
        raise ToolInputError(f"not a file: {args['path']!r}")
    text = (await asyncio.to_thread(target.read_bytes)).decode("utf-8", errors="replace")
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + f"\n[truncated: showing {MAX_CHARS} of {len(text)} characters]"
    return ToolOutput(text)


FILE_READ = Tool(
    name="file.read",
    description=(
        "Read a UTF-8 text file. Paths start with files/ (the user's workspace files) "
        "or out/ (files produced in this run)."
    ),
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "e.g. files/notes.txt"}},
        "required": ["path"],
        "additionalProperties": False,
    },
    tier="read",
    fn=_read,
)
```

`usta/tools/builtin/todo.py`:

```python
"""todo: the run's task list (ADR-016). Full replacement on each call."""

from __future__ import annotations

from typing import Any

from usta.core.events import Event
from usta.core.run import TodoItem
from usta.tools.registry import Tool, ToolContext, ToolOutput


async def _todo(args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
    ctx.run.todo = [TodoItem(**item) for item in args["items"]]
    rendered = "\n".join(f"[{i.status}] {i.content}" for i in ctx.run.todo) or "(empty)"
    event = Event(
        run_id=ctx.run.id,
        type="todo_updated",
        data={"items": [i.model_dump() for i in ctx.run.todo]},
    )
    return ToolOutput(rendered, event=event)


TODO = Tool(
    name="todo",
    description=(
        "Replace this run's task list. Use it for tasks with three or more steps; "
        "keep exactly one item in_progress and mark items done as you finish them."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "minLength": 1},
                        "status": {"enum": ["pending", "in_progress", "done"]},
                    },
                    "required": ["content", "status"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    },
    tier="local",
    fn=_todo,
)
```

`usta/tools/builtin/__init__.py`:

```python
from usta.tools.builtin.files import FILE_READ
from usta.tools.builtin.todo import TODO
from usta.tools.registry import Tool


def builtin_tools() -> list[Tool]:
    return [FILE_READ, TODO]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/tools tests/test_layout.py -q && uv run lint-imports`
Expected: all pass, and the contracts are kept (tools import only core and ports).

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add usta/tools tests/tools tests/fakes.py
git commit -m "feat(tools): registry, pipeline with intent/done audit, file.read, todo"
```

---

### Task 9: Own engine: loop, budgets, stop reasons, resume

**Files:**
- Create: `usta/engines/own/prompt.py`, `usta/engines/own/loop.py`
- Test: `tests/engines/__init__.py`, `tests/engines/test_own_loop.py`

**Interfaces:**
- Consumes: `RunContext`, `Budget`, `RunState`, `Event`, `PendingQuestion`, `ProviderQuotaError`, and `make_context` / `InMemoryStore` / `FakeClock` / `ECHO` in tests.
- Produces:
  - `SYSTEM_PROMPT` and `PROMPT_VERSION` (`"own-" + sha256[:12]`)
  - `build_request(run, tools) -> ModelRequest`
  - `OwnEngine(budget, *, clock=time.monotonic)` with `name = "own"` and `run(run, ctx) -> AsyncIterator[Event]`, which implements `EnginePort`

Loop contract:
1. The loop sets `status=running` and yields `run_started`.
2. Tool calls left without results are executed first.
3. Each step: tick the active clock, then check cancel, then the budget (`max_turns`, then `timeout`, then cost, which parks `awaiting_user` with a budget question). Then call the model, `record`, checkpoint, and yield `model_call`.
4. A `refusal` or `max_tokens` stop finishes with `error` and an explicit detail. A response with no tool calls finishes with `done`.
5. Otherwise the loop executes the tool calls sequentially, appends one tool-results message, checkpoints, and yields `step_done`.
6. `ProviderQuotaError` finishes with `provider_quota`. Any other exception is logged and finishes with `error`.
7. Every finish sets the reason, checkpoints, and yields `Event.finished(run)`.

- [ ] **Step 1: Write the failing test.** Create an empty `tests/engines/__init__.py`. Then `tests/engines/test_own_loop.py`:

```python
from pathlib import Path

from usta.core.budget import Budget
from usta.core.errors import ProviderQuotaError
from usta.core.messages import Message, ToolCall
from usta.core.model import ModelResponse, Usage
from usta.core.run import RunState, RunStatus, StopReason
from usta.engines.own.loop import OwnEngine
from usta.engines.own.prompt import PROMPT_VERSION
from usta.models.fake import call, reply
from tests.fakes import FakeClock, InMemoryStore, make_context


async def drive(script, tmp_path: Path, *, budget: Budget = Budget(), clock=None, run: RunState | None = None):
    store = InMemoryStore()
    ctx, model = make_context(script, store, tmp_path)
    run = run or RunState.new(id="r1", user_id="u1", task="Tapşırıq", engine="own", cost_cap_usd=budget.cost_step_usd)
    await store.create(run)
    engine = OwnEngine(budget, clock=clock) if clock else OwnEngine(budget)
    events = [ev async for ev in engine.run(run, ctx)]
    return run, events, model, store


async def test_text_reply_finishes_done(tmp_path: Path) -> None:
    run, events, model, store = await drive([reply("Hazırdır.")], tmp_path)
    assert run.stop_reason == StopReason.DONE and run.final_text() == "Hazırdır."
    assert [e.type for e in events] == ["run_started", "model_call", "finished"]
    assert (await store.load("r1")).stop_reason == StopReason.DONE  # checkpointed
    req = model.requests[0]
    assert req.system[0].cache and req.prompt_version == PROMPT_VERSION
    assert [t.name for t in req.tools] == ["test.echo"]
    assert (req.run_id, req.user_id) == ("r1", "u1")


async def test_tool_call_then_reply(tmp_path: Path) -> None:
    run, events, model, _ = await drive([call("test.echo", {"text": "bir"}), reply("ok")], tmp_path)
    assert run.stop_reason == StopReason.DONE and run.turns == 2
    assert [e.type for e in events] == [
        "run_started", "model_call", "tool_call", "tool_result", "step_done", "model_call", "finished",
    ]
    last_sent = model.requests[1].messages[-1]
    assert last_sent.role == "user" and last_sent.tool_results()[0].content == "echo: bir"


async def test_parallel_calls_produce_one_results_message_in_order(tmp_path: Path) -> None:
    both = ModelResponse(
        message=Message(
            role="assistant",
            content=(
                ToolCall(id="a", name="test.echo", input={"text": "1"}),
                ToolCall(id="b", name="test.echo", input={"text": "2"}),
            ),
        ),
        usage=Usage(input_tokens=10, output_tokens=5),
        stop="tool_use",
        model="fake-model",
    )
    run, *_ = await drive([both, reply("ok")], tmp_path)
    results = run.messages[2].tool_results()
    assert [r.call_id for r in results] == ["a", "b"]


async def test_max_turns(tmp_path: Path) -> None:
    script = [call("test.echo", {"text": str(i)}) for i in range(3)]
    run, events, model, _ = await drive(script, tmp_path, budget=Budget(max_turns=2, cost_step_usd=100))
    assert run.stop_reason == StopReason.MAX_TURNS and len(model.requests) == 2
    assert events[-1].data["stop_reason"] == "max_turns"


async def test_cost_cap_parks_and_asks_to_continue(tmp_path: Path) -> None:
    script = [call("test.echo", {"text": str(i)}) for i in range(3)]  # $0.30 per call
    run, events, model, store = await drive(script, tmp_path, budget=Budget(cost_step_usd=0.5))
    assert run.status == RunStatus.AWAITING_USER and run.stop_reason is None
    assert run.pending is not None and run.pending.kind == "budget" and "+$0.50" in run.pending.text
    assert len(model.requests) == 2
    assert events[-1].type == "parked"
    assert (await store.load("r1")).status == RunStatus.AWAITING_USER


async def test_active_time_limit(tmp_path: Path) -> None:
    script = [call("test.echo", {"text": str(i)}) for i in range(5)]
    run, _, model, _ = await drive(
        script, tmp_path, budget=Budget(max_active_seconds=1200, cost_step_usd=100), clock=FakeClock(step=300)
    )
    assert run.stop_reason == StopReason.TIMEOUT and len(model.requests) == 1


async def test_cancel_request_stops_before_the_next_model_call(tmp_path: Path) -> None:
    store = InMemoryStore()
    ctx, model = make_context([reply("never")], store, tmp_path)
    run = RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    await store.create(run)
    await store.request_cancel("r1")
    _ = [e async for e in OwnEngine(Budget()).run(run, ctx)]
    assert run.stop_reason == StopReason.CANCELLED and model.requests == []


async def test_provider_quota(tmp_path: Path) -> None:
    run, *_ = await drive([ProviderQuotaError("Console cap reached")], tmp_path)
    assert run.stop_reason == StopReason.PROVIDER_QUOTA and "Console cap" in (run.stop_detail or "")


async def test_unexpected_error_is_an_explicit_error_stop(tmp_path: Path) -> None:
    run, events, *_ = await drive([RuntimeError("boom")], tmp_path)
    assert run.stop_reason == StopReason.ERROR and run.stop_detail == "RuntimeError: boom"
    assert events[-1].type == "finished"


async def test_refusal_and_max_tokens_never_execute_tools(tmp_path: Path) -> None:
    for stop, detail in [("refusal", "refused"), ("max_tokens", "max_tokens")]:
        truncated = call("test.echo", {"text": "x"}).model_copy(update={"stop": stop})
        run, _, _, store = await drive([truncated], tmp_path)
        assert run.stop_reason == StopReason.ERROR and detail in (run.stop_detail or "")
        assert store.tool_calls == []


async def test_made_up_tool_and_bad_arguments_are_fed_back_and_the_run_continues(tmp_path: Path) -> None:
    bad_args = ModelResponse(
        message=Message(role="assistant", content=(ToolCall(id="c2", name="test.echo", input={}, input_error="arguments are not valid JSON"),)),
        usage=Usage(),
        stop="tool_use",
        model="fake-model",
    )
    script = [call("fleet.delete_all", {}), bad_args, reply("Bağışlayın, düzəltdim.")]
    run, *_ = await drive(script, tmp_path, budget=Budget(cost_step_usd=100))
    assert run.stop_reason == StopReason.DONE
    errors = [m.tool_results()[0] for m in run.messages if m.role == "user" and m.tool_results()]
    assert all(r.is_error for r in errors) and "unknown tool" in errors[0].content
    assert "not valid JSON" in errors[1].content


async def test_resume_executes_tool_calls_left_without_results(tmp_path: Path) -> None:
    run = RunState.new(id="r1", user_id="u1", task="t", engine="own", cost_cap_usd=0.5)
    run.record(call("test.echo", {"text": "yarımçıq"}, id="c9"))  # crashed before tools ran
    run.status = RunStatus.RUNNING
    run, _, model, _ = await drive([reply("bitdi")], tmp_path, run=run)
    assert run.stop_reason == StopReason.DONE
    sent = model.requests[0].messages[-1]
    assert sent.tool_results()[0].call_id == "c9" and sent.tool_results()[0].content == "echo: yarımçıq"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/engines -q`
Expected: `ModuleNotFoundError: No module named 'usta.engines.own.loop'`.

- [ ] **Step 3: Implement.** `usta/engines/own/prompt.py`:

```python
"""System prompt for engine=own. English instructions (ADR-030); the Azerbaijani style
examples and skill index join the cached prefix in M1/M3."""

import hashlib

SYSTEM_PROMPT = """\
You are Usta, a work agent for a telematics and security company in Azerbaijan.
You complete multi-step tasks with the tools provided and finish with a short answer.

- Reply in the user's language. Azerbaijani is the default.
- Workspace files are under files/; files produced in this run are under out/.
- For tasks with three or more steps, keep a task list with the todo tool and update it as you go.
- If a tool returns an error, read it and adjust; do not repeat the same failing call.
- When the task is done, reply with the result and make no further tool calls.
"""

PROMPT_VERSION = "own-" + hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]
```

`usta/engines/own/loop.py`:

```python
"""Usta's own asyncio turn loop (SPEC §4.1). M0: no context management, sequential tools."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable

from usta.core.budget import Budget
from usta.core.errors import ProviderQuotaError
from usta.core.events import Event
from usta.core.messages import ToolCall
from usta.core.model import ModelRequest, SystemBlock, ToolSpec
from usta.core.run import PendingQuestion, RunState, RunStatus, StopReason
from usta.engines.own.prompt import PROMPT_VERSION, SYSTEM_PROMPT
from usta.ports import RunContext

log = logging.getLogger(__name__)


def build_request(run: RunState, tools: tuple[ToolSpec, ...]) -> ModelRequest:
    return ModelRequest(
        role="main",
        system=(SystemBlock(text=SYSTEM_PROMPT, cache=True),),
        messages=tuple(run.messages),
        tools=tools,
        prompt_version=PROMPT_VERSION,
        run_id=run.id,
        user_id=run.user_id,
    )


class _ActiveTimer:
    """Adds wall-clock time to run.active_seconds while the loop runs; parked time never counts."""

    def __init__(self, run: RunState, clock: Callable[[], float]) -> None:
        self._run = run
        self._clock = clock
        self._last = clock()

    def tick(self) -> None:
        now = self._clock()
        self._run.active_seconds += now - self._last
        self._last = now


class OwnEngine:
    name = "own"

    def __init__(self, budget: Budget, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._budget = budget
        self._clock = clock

    async def run(self, run: RunState, ctx: RunContext) -> AsyncIterator[Event]:
        timer = _ActiveTimer(run, self._clock)
        run.status = RunStatus.RUNNING
        yield Event(run_id=run.id, type="run_started", data={"turns": run.turns})
        try:
            if pending := run.pending_tool_calls():  # crashed between checkpoints
                async for ev in self._execute(pending, run, ctx):
                    yield ev
                timer.tick()
                await ctx.store.checkpoint(run)
            while True:
                timer.tick()
                if await ctx.store.cancel_requested(run.id):
                    yield await self._finish(run, ctx, timer, StopReason.CANCELLED, "cancelled by user")
                    return
                limit = self._budget.check(run)
                if limit == "max_turns":
                    yield await self._finish(run, ctx, timer, StopReason.MAX_TURNS, f"{run.turns} turns")
                    return
                if limit == "timeout":
                    detail = f"{run.active_seconds:.0f}s of active time"
                    yield await self._finish(run, ctx, timer, StopReason.TIMEOUT, detail)
                    return
                if limit == "cost":
                    run.park(
                        RunStatus.AWAITING_USER,
                        PendingQuestion(
                            kind="budget",
                            text=(
                                f"This run has spent ${run.cost_usd:.2f} of its "
                                f"${run.cost_cap_usd:.2f} budget. Continue with "
                                f"+${self._budget.cost_step_usd:.2f}?"
                            ),
                        ),
                    )
                    await ctx.store.checkpoint(run)
                    yield Event.parked(run)
                    return

                resp = await ctx.models.complete(build_request(run, ctx.tools.specs()))
                run.record(resp)
                timer.tick()
                await ctx.store.checkpoint(run)
                yield Event(
                    run_id=run.id,
                    type="model_call",
                    data={
                        "turn": run.turns,
                        "model": resp.model,
                        "stop": resp.stop,
                        "cost_usd": resp.cost_usd,
                        "usage": resp.usage.model_dump(),
                    },
                )
                if resp.stop == "refusal":
                    yield await self._finish(run, ctx, timer, StopReason.ERROR, "model refused the request")
                    return
                if resp.stop == "max_tokens":
                    detail = "model output hit max_tokens before finishing"
                    yield await self._finish(run, ctx, timer, StopReason.ERROR, detail)
                    return
                calls = resp.tool_calls()
                if not calls:
                    yield await self._finish(run, ctx, timer, StopReason.DONE)
                    return
                async for ev in self._execute(calls, run, ctx):
                    yield ev
                timer.tick()
                await ctx.store.checkpoint(run)
                yield Event(
                    run_id=run.id,
                    type="step_done",
                    data={"turn": run.turns, "cost_usd": round(run.cost_usd, 6)},
                )
        except ProviderQuotaError as e:
            yield await self._finish(run, ctx, timer, StopReason.PROVIDER_QUOTA, str(e))
        except Exception as e:
            log.exception("run %s failed", run.id)
            yield await self._finish(run, ctx, timer, StopReason.ERROR, f"{type(e).__name__}: {e}")

    async def _execute(
        self, calls: list[ToolCall], run: RunState, ctx: RunContext
    ) -> AsyncIterator[Event]:
        results = []
        for call in calls:  # sequential; parallel execution is a later optimisation
            yield Event(
                run_id=run.id,
                type="tool_call",
                data={"call_id": call.id, "name": call.name, "input": call.input},
            )
            outcome = await ctx.tools.handle(call, run)
            results.append(outcome.result)
            if outcome.event is not None:
                yield outcome.event
            yield Event(
                run_id=run.id,
                type="tool_result",
                data={
                    "call_id": call.id,
                    "name": call.name,
                    "is_error": outcome.result.is_error,
                    "chars": len(outcome.result.content),
                },
            )
        run.append_tool_results(results)

    async def _finish(
        self,
        run: RunState,
        ctx: RunContext,
        timer: _ActiveTimer,
        reason: StopReason,
        detail: str | None = None,
    ) -> Event:
        timer.tick()
        run.finish(reason, detail)
        await ctx.store.checkpoint(run)
        return Event.finished(run)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/engines -q && uv run lint-imports`
Expected: `12 passed`, and the contracts are kept (the engine imports only core and ports).

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add usta/engines tests/engines
git commit -m "feat(engine): own loop with budgets, explicit stop reasons and resume"
```

---

### Task 10: Run worker (submit, execute, budget answer, cancel, recover)

**Files:**
- Modify: `usta/worker.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `RunStore`, `EnginePort`, `RunContext`, `Budget`, `RunState`, `Event`, `UserBudgetExceeded`.
- Produces: `Worker(store, engine, ctx, budget, *, engine_name: str, user_monthly_cap_usd: float, on_event: Callable[[Event], Awaitable[None]] | None = None)` with:
  - `async submit(user_id, task) -> RunState`, which raises `ValueError` for an empty task and `UserBudgetExceeded` over the monthly cap
  - `async execute(run_id) -> RunState`, a no-op for finished or parked runs
  - `async answer_budget(run_id, approve: bool) -> RunState`
  - `async cancel(run_id) -> RunState`
  - `async recover() -> list[str]`, which resumes `running` and `queued` runs

  Every event is persisted with `store.append_event` and then passed to `on_event`.

- [ ] **Step 1: Write the failing test** `tests/test_worker.py`:

```python
from pathlib import Path

import pytest

from usta.core.audit import ModelCallRecord
from usta.core.budget import Budget
from usta.core.errors import UserBudgetExceeded
from usta.core.events import Event
from usta.core.model import Usage
from usta.core.run import RunStatus, StopReason
from usta.engines.own.loop import OwnEngine
from usta.models.fake import call, reply
from usta.worker import Worker
from tests.fakes import InMemoryStore, make_context

BUDGET = Budget(cost_step_usd=0.5)


def make_worker(script, tmp_path: Path, *, cap: float = 10.0, on_event=None):
    store = InMemoryStore()
    ctx, model = make_context(script, store, tmp_path)
    worker = Worker(
        store, OwnEngine(BUDGET), ctx, BUDGET,
        engine_name="own", user_monthly_cap_usd=cap, on_event=on_event,
    )
    return worker, store, model, ctx


async def test_submit_and_execute_persists_and_forwards_events(tmp_path: Path) -> None:
    seen: list[Event] = []

    async def on_event(ev: Event) -> None:
        seen.append(ev)

    worker, store, _, _ = make_worker([reply("Hazır.")], tmp_path, on_event=on_event)
    run = await worker.submit("u1", "Hesabat hazırla")
    assert run.status == RunStatus.QUEUED and run.cost_cap_usd == 0.5 and run.engine == "own"
    final = await worker.execute(run.id)
    assert final.stop_reason == StopReason.DONE
    assert [e.type for e in store.events] == ["run_started", "model_call", "finished"]
    assert seen == store.events


async def test_submit_refuses_empty_task_and_exhausted_monthly_budget(tmp_path: Path) -> None:
    worker, store, _, _ = make_worker([], tmp_path, cap=1.0)
    with pytest.raises(ValueError):
        await worker.submit("u1", "   ")
    await store.model_call(
        ModelCallRecord(
            run_id="old", user_id="u1", role="main", provider="fake", model="m", prompt_version="p",
            attempt=1, request={}, response=None, error=None, usage=Usage(), cost_usd=1.0, latency_ms=1,
        )
    )
    with pytest.raises(UserBudgetExceeded):
        await worker.submit("u1", "yenə")


async def test_budget_park_then_approve_continues(tmp_path: Path) -> None:
    script = [call("test.echo", {"text": str(i)}) for i in range(2)] + [reply("bitdi")]
    worker, store, _, _ = make_worker(script, tmp_path)
    run = await worker.execute((await worker.submit("u1", "t")).id)
    assert run.status == RunStatus.AWAITING_USER
    assert await worker.execute(run.id) == await store.load(run.id)  # parked: no-op
    run = await worker.answer_budget(run.id, approve=True)
    assert run.stop_reason == StopReason.DONE and run.cost_cap_usd == pytest.approx(1.0)


async def test_budget_park_then_decline(tmp_path: Path) -> None:
    script = [call("test.echo", {"text": str(i)}) for i in range(2)]
    worker, store, _, _ = make_worker(script, tmp_path)
    run = await worker.execute((await worker.submit("u1", "t")).id)
    run = await worker.answer_budget(run.id, approve=False)
    assert run.stop_reason == StopReason.BUDGET_DECLINED
    assert store.events[-1].type == "finished"
    with pytest.raises(ValueError):
        await worker.answer_budget(run.id, approve=True)


async def test_cancel_parked_run_finishes_it_and_cancel_running_sets_flag(tmp_path: Path) -> None:
    script = [call("test.echo", {"text": str(i)}) for i in range(2)]
    worker, store, _, _ = make_worker(script, tmp_path)
    parked = await worker.execute((await worker.submit("u1", "t")).id)
    assert (await worker.cancel(parked.id)).stop_reason == StopReason.CANCELLED

    running = await worker.submit("u1", "t2")
    running.status = RunStatus.RUNNING
    await store.checkpoint(running)
    await worker.cancel(running.id)
    assert await store.cancel_requested(running.id)


async def test_recover_resumes_a_run_that_crashed_after_a_checkpoint(tmp_path: Path) -> None:
    worker, store, _, ctx = make_worker([call("test.echo", {"text": "bir"}), reply("hazır")], tmp_path)
    run = await worker.submit("u1", "echo et")
    # Simulate a process crash right after the model call was checkpointed.
    events = OwnEngine(BUDGET).run(await store.load(run.id), ctx)
    async for ev in events:
        if ev.type == "model_call":
            break
    await events.aclose()
    assert (await store.load(run.id)).status == RunStatus.RUNNING
    assert store.tool_calls == []  # the tool never ran

    assert await worker.recover() == [run.id]
    final = await store.load(run.id)
    assert final.stop_reason == StopReason.DONE and final.final_text() == "hazır"
    assert [r.phase for r in store.tool_calls] == ["intent", "done"]  # executed exactly once
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_worker.py -q`
Expected: `ImportError: cannot import name 'Worker' from 'usta.worker'`.

- [ ] **Step 3: Implement** `usta/worker.py`:

```python
"""In-process run worker (ADR-014). Runs are Postgres rows; parked runs are rows, not tasks."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from usta.core.budget import Budget
from usta.core.errors import UserBudgetExceeded
from usta.core.events import Event
from usta.core.run import RunState, RunStatus, StopReason
from usta.ports import EnginePort, RunContext, RunStore

EventCallback = Callable[[Event], Awaitable[None]]


class Worker:
    def __init__(
        self,
        store: RunStore,
        engine: EnginePort,
        ctx: RunContext,
        budget: Budget,
        *,
        engine_name: str,
        user_monthly_cap_usd: float,
        on_event: EventCallback | None = None,
    ) -> None:
        self._store = store
        self._engine = engine
        self._ctx = ctx
        self._budget = budget
        self._engine_name = engine_name
        self._user_cap = user_monthly_cap_usd
        self._on_event = on_event

    async def submit(self, user_id: str, task: str) -> RunState:
        if not task.strip():
            raise ValueError("task is empty")
        spent = await self._store.user_month_cost(user_id)
        if spent >= self._user_cap:
            raise UserBudgetExceeded(
                f"user {user_id!r} has spent ${spent:.2f} of ${self._user_cap:.2f} this month"
            )
        run = RunState.new(
            id=str(uuid.uuid4()),
            user_id=user_id,
            task=task,
            engine=self._engine_name,
            cost_cap_usd=self._budget.cost_step_usd,
        )
        await self._store.create(run)
        return run

    async def execute(self, run_id: str) -> RunState:
        run = await self._store.load(run_id)
        if run.is_finished or run.is_parked:
            return run
        async for event in self._engine.run(run, self._ctx):
            await self._emit(event, run.user_id)
        return run

    async def answer_budget(self, run_id: str, approve: bool) -> RunState:
        run = await self._store.load(run_id)
        if (
            run.status != RunStatus.AWAITING_USER
            or run.pending is None
            or run.pending.kind != "budget"
        ):
            raise ValueError(f"run {run_id} is not waiting for a budget answer")
        if not approve:
            run.finish(StopReason.BUDGET_DECLINED, "user declined to extend the budget")
            await self._store.checkpoint(run)
            await self._emit(Event.finished(run), run.user_id)
            return run
        run.cost_cap_usd += self._budget.cost_step_usd
        run.pending = None
        run.status = RunStatus.QUEUED
        await self._store.checkpoint(run)
        return await self.execute(run_id)

    async def cancel(self, run_id: str) -> RunState:
        run = await self._store.load(run_id)
        if run.is_finished:
            return run
        if run.is_parked or run.status == RunStatus.QUEUED:
            run.finish(StopReason.CANCELLED, "cancelled by user")
            await self._store.checkpoint(run)
            await self._emit(Event.finished(run), run.user_id)
            return run
        await self._store.request_cancel(run_id)  # running: the loop stops at its next step
        return run

    async def recover(self) -> list[str]:
        """On startup: resume runs a crash left running or queued (ADR-014 rule 3)."""
        run_ids = await self._store.ids_with_status(RunStatus.RUNNING, RunStatus.QUEUED)
        for run_id in run_ids:
            await self.execute(run_id)
        return run_ids

    async def _emit(self, event: Event, user_id: str) -> None:
        await self._store.append_event(event, user_id)
        if self._on_event is not None:
            await self._on_event(event)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_worker.py -q && uv run lint-imports`
Expected: `6 passed`, and the contracts are kept (the worker imports only core and ports).

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add usta/worker.py tests/test_worker.py
git commit -m "feat(worker): submit, execute, budget answer, cancel, crash recovery"
```

---

### Task 11: Postgres schema, migration 0001 and DB roles ⛔ review gate

**Files:**
- Create: `alembic.ini`, `usta/store/tables.py`, `usta/store/migrations/env.py`, `usta/store/migrations/script.py.mako`, `usta/store/migrations/versions/0001_initial.py`
- Create: `tests/conftest.py`
- Test: `tests/store/__init__.py`, `tests/store/test_schema.py`
- Modify: `README.md` (add the `alembic upgrade` line)

**Interfaces:**
- Produces:
  - SQLAlchemy Core tables `users`, `runs`, `run_checkpoints`, `model_calls`, `tool_calls`, `run_events` in `usta.store.tables`
  - NOLOGIN group roles `usta_app` (full rights on run tables; only `SELECT, INSERT` on audit tables) and `usta_purge` (`SELECT, DELETE` on audit tables)
  - Test fixtures `migrated_db` (session, owner URL), `clean_db` (truncated, owner URL), `db_engine` (owner `AsyncEngine`), `app_role_engine` (`AsyncEngine` running as `usta_app`)

**Schema (review this before Step 1; SPEC §13 requires a review before migrating):**

| Table | Columns | Notes |
|---|---|---|
| `users` | `id text PK`, `display_name text`, `scopes jsonb default '[]'`, `created_at timestamptz` | Scopes are used from M2 (run tokens). |
| `runs` | `id uuid PK`, `user_id text FK users`, `task text`, `engine text`, `profile text`, `status text`, `stop_reason text NULL`, `cancel_requested bool`, `turns int`, `cost_usd double`, `created_at`, `updated_at`, `finished_at NULL` | CHECKs: status ∈ 6 values; stop_reason ∈ 9 values; `(status='finished') = (stop_reason IS NOT NULL)` (P6). Indexes: `(status)`, `(user_id, created_at)`. This is a queryable summary; the full state lives in checkpoints. |
| `run_checkpoints` | `run_id uuid FK runs ON DELETE CASCADE`, `seq int`, `state jsonb`, `created_at` | PK `(run_id, seq)`. One row per step (Plan Decision 10). |
| `model_calls` (audit) | `id uuid PK`, `run_id uuid NULL`, `user_id text NULL`, `role`, `provider`, `model`, `prompt_version`, `attempt int`, `request jsonb`, `response jsonb NULL`, `error text NULL`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens` (int), `cost_usd double`, `latency_ms int`, `created_at = clock_timestamp()` | No FKs, so audit rows outlive purged runs. Indexes: `(run_id)`, `(user_id, created_at)`. |
| `tool_calls` (audit) | `id uuid PK`, `run_id uuid`, `user_id text`, `call_id text`, `tool text`, `phase text CHECK ∈ (intent, done)`, `input jsonb`, `output text NULL`, `is_error bool NULL`, `latency_ms int NULL`, `created_at` | Index `(run_id, call_id)`. |
| `run_events` (audit) | `id uuid PK`, `run_id uuid`, `user_id text`, `type text`, `data jsonb`, `created_at` | Index `(run_id, created_at)`. The run view reads this. |

Audit tables use app-generated UUIDs, so the app role never needs sequence grants. Audit `created_at` uses `clock_timestamp()`, so rows written in one transaction keep their order.

**Schema decisions (grilling round 1, approved by Fariz 2026-10-08):**
1. `runs.status` CHECK lists all 6 `RunStatus` values (matches the enum, incl. M2's `awaiting_approval` / `unknown_outcome`).
2. No cross-process run lease in M0. The `run_checkpoints` PK `(run_id, seq)` makes a second writer fail loudly. Nullable `lease_owner` / `lease_until` columns are a later additive migration (see Known Limitations).
3. Costs stay `double precision` (Plan Decision 11); the README states why.
4. `user_month_cost` sums `model_calls.cost_usd` (the audit table is the P7 source of truth), not `runs.cost_usd`.
5. The month boundary is UTC: `created_at >= date_trunc('month', now() AT TIME ZONE 'UTC')`.
6. `users.id` gets `CHECK (id ~ '^[a-z0-9][a-z0-9_-]{0,63}$')`; app code also validates before insert for a clear message.
7. Audit append-only via grants only (no trigger); `tests/store/test_schema.py` proves `usta_app` cannot `UPDATE`, `DELETE` or `TRUNCATE` audit tables.
8. `model_calls.request` stores the full request in M0; revisit size at M3 with real numbers.
9. Every checkpoint writes the `run_checkpoints` row and updates the `runs` summary in one transaction (Task 12 rule).

**Schema decisions (grilling round 2, approved by Fariz 2026-10-08):**
10. Keep every per-step `run_checkpoints` row in M0; pruning is an M3 concern.
11. Replace the plain `runs (status)` index with a partial index `ON runs (status) WHERE status <> 'finished'` (what `recover` scans).
12. Migrations run as the owner role. `usta_app` gets `SELECT, INSERT, UPDATE` on `users`, `runs`, `run_checkpoints` (no `DELETE`); `SELECT, INSERT` only on audit tables.
13. `usta_purge` gets `SELECT, DELETE` on `runs` (cascades to checkpoints) and on the audit tables. The `usta purge` CLI stays deferred (Plan Decision 15).
14. `usta_app` / `usta_purge` are `NOLOGIN` group roles created by the migration. Dev login users that are members of them are created in `deploy/postgres/init.sql`, with dev-only passwords in `.env.example`; prod creates its own.

- [ ] **Step 0: STOP. Show Fariz the schema table above and get explicit approval** (or changes) before writing the migration. If anything changes, update this table first.

- [ ] **Step 1: Write the fixtures and the failing test.** `tests/conftest.py`:

```python
"""Shared fixtures. Postgres tests need USTA_TEST_DATABASE_URL: an owner role on a throwaway DB."""

import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine

TABLES = "users, runs, run_checkpoints, model_calls, tool_calls, run_events"


async def _execute(url: str, *statements: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            for statement in statements:
                await conn.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def migrated_db() -> str:
    url = os.environ.get("USTA_TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "USTA_TEST_DATABASE_URL is not set. Start Postgres with "
            "`docker compose -f deploy/compose.dev.yml up -d` and load .env (see .env.example)."
        )
    asyncio.run(_execute(url, "DROP SCHEMA IF EXISTS public CASCADE", "CREATE SCHEMA public"))
    os.environ["USTA_MIGRATION_DATABASE_URL"] = url
    command.upgrade(Config("alembic.ini"), "head")
    return url


@pytest.fixture
def clean_db(migrated_db: str) -> str:
    asyncio.run(_execute(migrated_db, f"TRUNCATE {TABLES} CASCADE"))
    return migrated_db


@pytest.fixture
async def db_engine(clean_db: str):
    engine = create_async_engine(clean_db)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app_role_engine(clean_db: str):
    """Runs as usta_app, so store tests prove the app role's grants are enough."""
    engine = create_async_engine(clean_db)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_role(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("SET ROLE usta_app")
        cursor.close()

    yield engine
    await engine.dispose()
```

Create an empty `tests/store/__init__.py`. Then `tests/store/test_schema.py`:

```python
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

pytestmark = pytest.mark.pg

INSERT_EVENT = (
    "INSERT INTO run_events (id, run_id, user_id, type, data) "
    "VALUES (gen_random_uuid(), gen_random_uuid(), 'u1', 'finished', '{}')"
)


@pytest.mark.parametrize("table", ["model_calls", "tool_calls", "run_events"])
async def test_app_role_cannot_update_or_delete_audit_rows(app_role_engine, table: str) -> None:
    for statement in (f"UPDATE {table} SET created_at = now()", f"DELETE FROM {table}"):
        async with app_role_engine.connect() as conn:
            with pytest.raises(DBAPIError, match="permission denied"):
                await conn.execute(text(statement))


async def test_app_role_can_insert_and_select_audit_rows(app_role_engine) -> None:
    async with app_role_engine.begin() as conn:
        await conn.execute(text(INSERT_EVENT))
        assert (await conn.execute(text("SELECT count(*) FROM run_events"))).scalar_one() == 1


async def test_purge_role_can_delete_audit_rows(db_engine) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(text(INSERT_EVENT))
        await conn.execute(text("SET LOCAL ROLE usta_purge"))
        assert (await conn.execute(text("DELETE FROM run_events"))).rowcount == 1


async def test_finished_run_needs_a_stop_reason(db_engine) -> None:
    async with db_engine.begin() as conn:
        await conn.execute(text("INSERT INTO users (id, display_name) VALUES ('u1', 'U')"))
    with pytest.raises(IntegrityError, match="ck_runs_finished_has_reason"):
        async with db_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO runs (id, user_id, task, engine, profile, status) "
                    "VALUES (gen_random_uuid(), 'u1', 't', 'own', 'test', 'finished')"
                )
            )


def test_table_definitions_match_migrations(migrated_db: str) -> None:
    command.check(Config("alembic.ini"))  # raises if tables.py and migrations disagree
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `set -a; source .env; set +a; uv run pytest tests/store/test_schema.py -q`
Expected: an error in `migrated_db`, because `alembic.ini` does not exist yet (e.g. `CommandError: No 'script_location' key found`).

- [ ] **Step 3: Alembic config.** `alembic.ini`:

```ini
[alembic]
script_location = usta/store/migrations
prepend_sys_path = .
```

`usta/store/migrations/env.py`:

```python
"""Alembic env: async engine, owner role URL from USTA_MIGRATION_DATABASE_URL."""

import asyncio
import os

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from usta.store.tables import metadata

target_metadata = metadata


def _url() -> str:
    url = os.environ.get("USTA_MIGRATION_DATABASE_URL")
    if not url:
        raise RuntimeError("USTA_MIGRATION_DATABASE_URL is not set (owner role; see .env.example)")
    return url


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_online())
```

`usta/store/migrations/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 4: Table definitions.** `usta/store/tables.py`:

```python
"""SQLAlchemy Core tables. Must match the migrations (`alembic check` in the test suite)."""

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

metadata = MetaData()


def _ts(name: str, default: str | None = "now()", nullable: bool = False) -> Column:
    return Column(
        name,
        TIMESTAMP(timezone=True),
        nullable=nullable,
        server_default=text(default) if default else None,
    )


def _uuid(name: str, *args, **kw) -> Column:
    return Column(name, Uuid(as_uuid=False), *args, **kw)


users = Table(
    "users",
    metadata,
    Column("id", Text, primary_key=True),
    Column("display_name", Text, nullable=False),
    Column("scopes", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    _ts("created_at"),
)

runs = Table(
    "runs",
    metadata,
    _uuid("id", primary_key=True),
    Column("user_id", Text, ForeignKey("users.id"), nullable=False),
    Column("task", Text, nullable=False),
    Column("engine", Text, nullable=False),
    Column("profile", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("stop_reason", Text, nullable=True),
    Column("cancel_requested", Boolean, nullable=False, server_default=text("false")),
    Column("turns", Integer, nullable=False, server_default=text("0")),
    Column("cost_usd", Float, nullable=False, server_default=text("0")),
    _ts("created_at"),
    _ts("updated_at"),
    _ts("finished_at", default=None, nullable=True),
    Index("ix_runs_status", "status"),
    Index("ix_runs_user_created", "user_id", "created_at"),
)

run_checkpoints = Table(
    "run_checkpoints",
    metadata,
    _uuid("run_id", ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
    Column("seq", Integer, primary_key=True),
    Column("state", JSONB, nullable=False),
    _ts("created_at"),
)

model_calls = Table(
    "model_calls",
    metadata,
    _uuid("id", primary_key=True),
    _uuid("run_id", nullable=True),
    Column("user_id", Text, nullable=True),
    Column("role", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("request", JSONB, nullable=False),
    Column("response", JSONB(none_as_null=True), nullable=True),
    Column("error", Text, nullable=True),
    Column("input_tokens", Integer, nullable=False),
    Column("output_tokens", Integer, nullable=False),
    Column("cache_read_tokens", Integer, nullable=False),
    Column("cache_write_tokens", Integer, nullable=False),
    Column("cost_usd", Float, nullable=False),
    Column("latency_ms", Integer, nullable=False),
    _ts("created_at", default="clock_timestamp()"),
    Index("ix_model_calls_run", "run_id"),
    Index("ix_model_calls_user_created", "user_id", "created_at"),
)

tool_calls = Table(
    "tool_calls",
    metadata,
    _uuid("id", primary_key=True),
    _uuid("run_id", nullable=False),
    Column("user_id", Text, nullable=False),
    Column("call_id", Text, nullable=False),
    Column("tool", Text, nullable=False),
    Column("phase", Text, nullable=False),
    Column("input", JSONB, nullable=False),
    Column("output", Text, nullable=True),
    Column("is_error", Boolean, nullable=True),
    Column("latency_ms", Integer, nullable=True),
    _ts("created_at", default="clock_timestamp()"),
    Index("ix_tool_calls_run_call", "run_id", "call_id"),
)

run_events = Table(
    "run_events",
    metadata,
    _uuid("id", primary_key=True),
    _uuid("run_id", nullable=False),
    Column("user_id", Text, nullable=False),
    Column("type", Text, nullable=False),
    Column("data", JSONB, nullable=False),
    _ts("created_at", default="clock_timestamp()"),
    Index("ix_run_events_run_created", "run_id", "created_at"),
)
```

- [ ] **Step 5: Migration.** `usta/store/migrations/versions/0001_initial.py`:

```python
"""initial schema: users, runs, checkpoints, append-only audit tables, DB roles

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

STATUSES = ("queued", "running", "awaiting_approval", "awaiting_user", "unknown_outcome", "finished")
STOP_REASONS = (
    "done", "verification_failed", "max_turns", "budget_declined", "timeout",
    "provider_quota", "cancelled", "interrupted", "error",
)
RUN_TABLES = "users, runs, run_checkpoints"
AUDIT_TABLES = "model_calls, tool_calls, run_events"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _ts(name: str, default: str = "now()") -> sa.Column:
    return sa.Column(name, sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text(default))


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("scopes", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        _ts("created_at"),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("task", sa.Text, nullable=False),
        sa.Column("engine", sa.Text, nullable=False),
        sa.Column("profile", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("stop_reason", sa.Text, nullable=True),
        sa.Column("cancel_requested", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("turns", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default=sa.text("0")),
        _ts("created_at"),
        _ts("updated_at"),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(_in("status", STATUSES), name="ck_runs_status"),
        sa.CheckConstraint(
            "stop_reason IS NULL OR " + _in("stop_reason", STOP_REASONS), name="ck_runs_stop_reason"
        ),
        sa.CheckConstraint(
            "(status = 'finished') = (stop_reason IS NOT NULL)", name="ck_runs_finished_has_reason"
        ),
    )
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_runs_user_created", "runs", ["user_id", "created_at"])
    op.create_table(
        "run_checkpoints",
        sa.Column("run_id", sa.Uuid, sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("seq", sa.Integer, primary_key=True),
        sa.Column("state", JSONB, nullable=False),
        _ts("created_at"),
    )
    op.create_table(
        "model_calls",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("run_id", sa.Uuid, nullable=True),
        sa.Column("user_id", sa.Text, nullable=True),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("prompt_version", sa.Text, nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("request", JSONB, nullable=False),
        sa.Column("response", JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("cache_read_tokens", sa.Integer, nullable=False),
        sa.Column("cache_write_tokens", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Float, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        _ts("created_at", "clock_timestamp()"),
    )
    op.create_index("ix_model_calls_run", "model_calls", ["run_id"])
    op.create_index("ix_model_calls_user_created", "model_calls", ["user_id", "created_at"])
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("run_id", sa.Uuid, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("call_id", sa.Text, nullable=False),
        sa.Column("tool", sa.Text, nullable=False),
        sa.Column("phase", sa.Text, nullable=False),
        sa.Column("input", JSONB, nullable=False),
        sa.Column("output", sa.Text, nullable=True),
        sa.Column("is_error", sa.Boolean, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        _ts("created_at", "clock_timestamp()"),
        sa.CheckConstraint("phase IN ('intent', 'done')", name="ck_tool_calls_phase"),
    )
    op.create_index("ix_tool_calls_run_call", "tool_calls", ["run_id", "call_id"])
    op.create_table(
        "run_events",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("run_id", sa.Uuid, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("data", JSONB, nullable=False),
        _ts("created_at", "clock_timestamp()"),
    )
    op.create_index("ix_run_events_run_created", "run_events", ["run_id", "created_at"])

    # Append-only audit, enforced by the database (ADR-029).
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'usta_app') THEN
            CREATE ROLE usta_app NOLOGIN;
          END IF;
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'usta_purge') THEN
            CREATE ROLE usta_purge NOLOGIN;
          END IF;
        END $$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO usta_app, usta_purge")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {RUN_TABLES} TO usta_app")
    op.execute(f"GRANT SELECT, INSERT ON {AUDIT_TABLES} TO usta_app")
    op.execute(f"GRANT SELECT, DELETE ON {AUDIT_TABLES} TO usta_purge")


def downgrade() -> None:
    # Roles are cluster-wide and may serve other databases, so they stay.
    for table in ("run_events", "tool_calls", "model_calls", "run_checkpoints", "runs", "users"):
        op.drop_table(table)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/store/test_schema.py -q`
Expected: `7 passed`, with `alembic check` reporting no drift. If `command.check` reports a type difference such as `Float` vs `DOUBLE_PRECISION`, fix `tables.py` so that both sides use the same type. Do not remove the check.

- [ ] **Step 7: README.** In `README.md`, after the `docker compose ... up -d` line, add:

```
    uv run alembic upgrade head     # owner role (USTA_MIGRATION_DATABASE_URL)
```

- [ ] **Step 8: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add alembic.ini usta/store tests/conftest.py tests/store README.md
git commit -m "feat(store): schema 0001 with append-only audit enforced by DB roles"
```

---

### Task 12: Postgres run store (`PgRunStore`)

**Files:**
- Create: `usta/store/pg.py`
- Test: `tests/store/test_pg_store.py`

**Interfaces:**
- Consumes: the tables from Task 11, `RunState`, `Event`, the audit records, `UnknownUser`, `UstaError`.
- Produces:
  - `PgRunStore(engine: AsyncEngine, *, profile: str)`, which implements `RunStore` and `AuditSink`
  - `add_user(user_id, display_name, scopes=())`, an upsert that validates `USER_ID`
  - `events(run_id) -> list[Event]`
  - `USER_ID` regex: `^[a-z0-9][a-z0-9_-]{0,31}$`, because the user id becomes a directory name

- [ ] **Step 1: Write the failing test** `tests/store/test_pg_store.py`:

```python
import uuid

import pytest
from sqlalchemy import text

from usta.core.audit import ModelCallRecord, ToolCallRecord
from usta.core.errors import UnknownUser, UstaError
from usta.core.events import Event
from usta.core.messages import Message, ToolCall
from usta.core.model import ModelResponse, Usage
from usta.core.run import RunState, RunStatus, StopReason
from usta.store.pg import PgRunStore

pytestmark = pytest.mark.pg
AZ_TASK = "Keçən həftənin yanacaq hesabatı: İSTİQAMƏT, IŞIQ — ğ ş ı ö ü ç ə"


@pytest.fixture
async def store(app_role_engine) -> PgRunStore:
    s = PgRunStore(app_role_engine, profile="test")
    await s.add_user("u1", "Test İstifadəçi", ["fleet:read"])
    return s


def new_run(user_id: str = "u1") -> RunState:
    return RunState.new(id=str(uuid.uuid4()), user_id=user_id, task=AZ_TASK, engine="own", cost_cap_usd=0.5)


def model_record(user_id: str, cost: float) -> ModelCallRecord:
    return ModelCallRecord(
        run_id=str(uuid.uuid4()), user_id=user_id, role="main", provider="fake", model="m",
        prompt_version="p", attempt=1, request={"q": "ə"}, response=None, error=None,
        usage=Usage(input_tokens=1), cost_usd=cost, latency_ms=3,
    )


async def test_create_then_load_round_trips_azerbaijani_text(store: PgRunStore) -> None:
    run = new_run()
    run.record(
        ModelResponse(
            message=Message(role="assistant", content=(ToolCall(id="c", name="file.read", input={"path": "files/ə.txt"}),)),
            usage=Usage(), stop="tool_use", model="m",
        )
    )
    await store.create(run)
    loaded = await store.load(run.id)
    assert loaded == run
    assert loaded.task == AZ_TASK


async def test_checkpoint_appends_and_updates_the_summary_row(store: PgRunStore, db_engine) -> None:
    run = new_run()
    await store.create(run)
    run.status, run.turns, run.cost_usd = RunStatus.RUNNING, 2, 0.25
    await store.checkpoint(run)
    run.finish(StopReason.DONE)
    await store.checkpoint(run)
    assert (await store.load(run.id)).stop_reason == StopReason.DONE
    async with db_engine.connect() as conn:
        seqs = (await conn.execute(text("SELECT seq FROM run_checkpoints WHERE run_id = :r ORDER BY seq"), {"r": run.id})).scalars().all()
        row = (await conn.execute(text("SELECT status, stop_reason, turns, cost_usd, finished_at FROM runs WHERE id = :r"), {"r": run.id})).one()
    assert seqs == [0, 1, 2]
    assert (row.status, row.stop_reason, row.turns, row.cost_usd) == ("finished", "done", 2, 0.25)
    assert row.finished_at is not None


async def test_ids_with_status_and_cancel_flag(store: PgRunStore) -> None:
    a, b = new_run(), new_run()
    await store.create(a)
    await store.create(b)
    b.status = RunStatus.RUNNING
    await store.checkpoint(b)
    assert await store.ids_with_status(RunStatus.RUNNING) == [b.id]
    assert set(await store.ids_with_status(RunStatus.RUNNING, RunStatus.QUEUED)) == {a.id, b.id}
    assert await store.cancel_requested(b.id) is False
    await store.request_cancel(b.id)
    assert await store.cancel_requested(b.id) is True


async def test_events_are_appended_in_order(store: PgRunStore) -> None:
    run = new_run()
    await store.create(run)
    for kind in ("run_started", "model_call", "finished"):
        await store.append_event(Event(run_id=run.id, type=kind, data={"t": "ə"}), "u1")
    assert [e.type for e in await store.events(run.id)] == ["run_started", "model_call", "finished"]


async def test_audit_rows_and_month_cost(store: PgRunStore, db_engine) -> None:
    for user, cost in [("u1", 0.1), ("u1", 0.2), ("u2", 5.0)]:
        await store.model_call(model_record(user, cost))
    old = model_record("u1", 9.0)
    await store.model_call(old)
    async with db_engine.begin() as conn:  # owner backdates one row to last month
        await conn.execute(text("UPDATE model_calls SET created_at = now() - interval '40 days' WHERE cost_usd = 9.0"))
    assert await store.user_month_cost("u1") == pytest.approx(0.3)
    assert await store.user_month_cost("nobody") == 0.0
    await store.tool_call(ToolCallRecord(run_id=str(uuid.uuid4()), user_id="u1", call_id="c", tool="todo", phase="intent", input={"items": []}))


async def test_unknown_user_is_a_clear_error(store: PgRunStore) -> None:
    with pytest.raises(UnknownUser, match="usta user ghost"):
        await store.create(new_run("ghost"))


@pytest.mark.parametrize("bad", ["../x", "Fariz", "", "a" * 33, "u 1"])
async def test_invalid_user_ids_are_refused(store: PgRunStore, bad: str) -> None:
    with pytest.raises(UstaError, match="invalid user id"):
        await store.add_user(bad, "x")


async def test_add_user_is_an_upsert(store: PgRunStore, db_engine) -> None:
    await store.add_user("u1", "Yeni ad", ["email:read"])
    async with db_engine.connect() as conn:
        row = (await conn.execute(text("SELECT display_name, scopes FROM users WHERE id = 'u1'"))).one()
    assert (row.display_name, row.scopes) == ("Yeni ad", ["email:read"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/store/test_pg_store.py -q`
Expected: `ModuleNotFoundError: No module named 'usta.store.pg'`.

- [ ] **Step 3: Implement** `usta/store/pg.py`:

```python
"""Postgres RunStore + AuditSink (ADR-014, ADR-029). Audit tables are insert-only for usta_app."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from usta.core.audit import ModelCallRecord, ToolCallRecord
from usta.core.errors import UnknownUser, UstaError
from usta.core.events import Event
from usta.core.run import RunState, RunStatus
from usta.store.tables import model_calls, run_checkpoints, run_events, runs, tool_calls, users

USER_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


class PgRunStore:
    def __init__(self, engine: AsyncEngine, *, profile: str) -> None:
        self._engine = engine
        self._profile = profile

    async def add_user(self, user_id: str, display_name: str, scopes: Iterable[str] = ()) -> None:
        if not USER_ID.match(user_id):
            raise UstaError(
                f"invalid user id {user_id!r}: use 1-32 of a-z 0-9 _ - (it becomes a directory name)"
            )
        stmt = pg_insert(users).values(id=user_id, display_name=display_name, scopes=list(scopes))
        stmt = stmt.on_conflict_do_update(
            index_elements=[users.c.id],
            set_={"display_name": stmt.excluded.display_name, "scopes": stmt.excluded.scopes},
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def create(self, run: RunState) -> None:
        try:
            async with self._engine.begin() as conn:
                await conn.execute(
                    insert(runs).values(
                        id=run.id,
                        user_id=run.user_id,
                        task=run.task,
                        engine=run.engine,
                        profile=self._profile,
                        status=run.status.value,
                        turns=run.turns,
                        cost_usd=run.cost_usd,
                    )
                )
                await conn.execute(
                    insert(run_checkpoints).values(run_id=run.id, seq=0, state=run.model_dump(mode="json"))
                )
        except IntegrityError as e:
            if "runs_user_id_fkey" in str(e.orig):
                raise UnknownUser(
                    f"unknown user {run.user_id!r}; add it with `usta user {run.user_id}`"
                ) from e
            raise

    async def load(self, run_id: str) -> RunState:
        async with self._engine.connect() as conn:
            state = (
                await conn.execute(
                    select(run_checkpoints.c.state)
                    .where(run_checkpoints.c.run_id == run_id)
                    .order_by(run_checkpoints.c.seq.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if state is None:
            raise KeyError(f"no run {run_id}")
        return RunState.model_validate(state)

    async def checkpoint(self, run: RunState) -> None:
        async with self._engine.begin() as conn:
            seq = (
                await conn.execute(
                    select(func.coalesce(func.max(run_checkpoints.c.seq), -1) + 1).where(
                        run_checkpoints.c.run_id == run.id
                    )
                )
            ).scalar_one()
            await conn.execute(
                insert(run_checkpoints).values(run_id=run.id, seq=seq, state=run.model_dump(mode="json"))
            )
            await conn.execute(
                update(runs)
                .where(runs.c.id == run.id)
                .values(
                    status=run.status.value,
                    stop_reason=run.stop_reason.value if run.stop_reason else None,
                    turns=run.turns,
                    cost_usd=run.cost_usd,
                    updated_at=func.now(),
                    finished_at=func.now() if run.is_finished else None,
                )
            )

    async def ids_with_status(self, *statuses: RunStatus) -> list[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                select(runs.c.id)
                .where(runs.c.status.in_([s.value for s in statuses]))
                .order_by(runs.c.created_at)
            )
            return [str(r) for r in rows.scalars()]

    async def request_cancel(self, run_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(update(runs).where(runs.c.id == run_id).values(cancel_requested=True))

    async def cancel_requested(self, run_id: str) -> bool:
        async with self._engine.connect() as conn:
            value = (
                await conn.execute(select(runs.c.cancel_requested).where(runs.c.id == run_id))
            ).scalar_one_or_none()
        return bool(value)

    async def append_event(self, event: Event, user_id: str) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(run_events).values(
                    id=str(uuid.uuid4()),
                    run_id=event.run_id,
                    user_id=user_id,
                    type=event.type,
                    data=event.data,
                )
            )

    async def events(self, run_id: str) -> list[Event]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                select(run_events.c.type, run_events.c.data)
                .where(run_events.c.run_id == run_id)
                .order_by(run_events.c.created_at)
            )
            return [Event(run_id=run_id, type=r.type, data=r.data) for r in rows]

    async def user_month_cost(self, user_id: str) -> float:
        async with self._engine.connect() as conn:
            total = (
                await conn.execute(
                    select(func.coalesce(func.sum(model_calls.c.cost_usd), 0.0)).where(
                        model_calls.c.user_id == user_id,
                        model_calls.c.created_at >= func.date_trunc("month", func.now()),
                    )
                )
            ).scalar_one()
        return float(total)

    async def model_call(self, rec: ModelCallRecord) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(model_calls).values(
                    id=str(uuid.uuid4()),
                    run_id=rec.run_id,
                    user_id=rec.user_id,
                    role=rec.role,
                    provider=rec.provider,
                    model=rec.model,
                    prompt_version=rec.prompt_version,
                    attempt=rec.attempt,
                    request=rec.request,
                    response=rec.response,
                    error=rec.error,
                    input_tokens=rec.usage.input_tokens,
                    output_tokens=rec.usage.output_tokens,
                    cache_read_tokens=rec.usage.cache_read_tokens,
                    cache_write_tokens=rec.usage.cache_write_tokens,
                    cost_usd=rec.cost_usd,
                    latency_ms=rec.latency_ms,
                )
            )

    async def tool_call(self, rec: ToolCallRecord) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                insert(tool_calls).values(
                    id=str(uuid.uuid4()),
                    run_id=rec.run_id,
                    user_id=rec.user_id,
                    call_id=rec.call_id,
                    tool=rec.tool,
                    phase=rec.phase,
                    input=rec.input,
                    output=rec.output,
                    is_error=rec.is_error,
                    latency_ms=rec.latency_ms,
                )
            )
```

Note: `ModelCallRecord.run_id` is typed `str | None`, but the column is `uuid`. Callers always pass a run UUID or `None`. The gateway gets `run_id` from `RunState.id`, which `Worker.submit` creates with `uuid4`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/store -q && uv run lint-imports`
Expected: all pass, as the `usta_app` role, so the grants are sufficient. The contracts are kept.

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add usta/store/pg.py tests/store/test_pg_store.py
git commit -m "feat(store): Postgres run store, checkpoints, events and audit writer"
```

---

### Task 13: Profiles, startup guards, composition root

**Files:**
- Create: `config/profiles/test.toml`, `config/profiles/dev-free.toml`, `config/profiles/dev-api.toml`, `config/profiles/dev-sub.toml`, `config/profiles/prod.toml`
- Create: `usta/app/config.py`, `usta/app/guards.py`, `usta/app/wiring.py`
- Test: `tests/app/__init__.py`, `tests/app/test_guards.py`, `tests/app/test_wiring.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `Settings` (env prefix `USTA_`): `profile`, `database_url` (both required), `user=""`, `config_dir=Path("config")`, `workspace_root=Path("workspaces")`
  - `RoleConfig(model, api_key_env=None, api_base=None, max_output_tokens=8192, effort=None)`, `BudgetConfig(max_turns=40, cost_cap_usd=0.5, max_active_seconds=1200, user_monthly_cap_usd=10.0)`, `Profile(name, engine, sandbox, bind="127.0.0.1", multi_user=False, roles, budget)`
  - `load_profile(name, config_dir) -> Profile`
  - `validate_startup(profile, catalog, env) -> None`, which raises a `ConfigError` that lists every problem
  - `App(profile, db, store, worker)` with `aclose()`
  - `build_model(model_id, entry, role_cfg, env) -> ModelPort`
  - `async build_app(settings, *, env=os.environ, model_overrides=None, on_event=None) -> App`

- [ ] **Step 1: Profiles.**

`config/profiles/test.toml`:

```toml
# T1/T3a: fake model, no network. The only profile allowed fake models and docker_hardened (P8).
engine = "own"
sandbox = "docker_hardened"

[roles.main]
model = "fake-model"

[roles.light]
model = "fake-model"
```

`config/profiles/dev-free.toml`:

```toml
# Own loop on a free-tier model via LiteLLM ($0; exercises R6). Model re-checked in Task 15.
engine = "own"
sandbox = "gvisor"

[roles.main]
model = "gemini/gemini-2.5-flash"
api_key_env = "GEMINI_API_KEY"
max_output_tokens = 8192

[roles.light]
model = "gemini/gemini-2.5-flash"
api_key_env = "GEMINI_API_KEY"
max_output_tokens = 4096
```

`config/profiles/dev-api.toml`:

```toml
# Own loop on the Anthropic API with a $20/month Console cap (ADR-013).
engine = "own"
sandbox = "gvisor"

[roles.main]
model = "claude-sonnet-5-5"
api_key_env = "ANTHROPIC_API_KEY"
max_output_tokens = 16000
effort = "medium"  # cost lever; measured in M3

[roles.light]
model = "claude-haiku-4-5"  # Haiku 4.5 rejects the effort parameter
api_key_env = "ANTHROPIC_API_KEY"
max_output_tokens = 4096
```

`config/profiles/dev-sub.toml`:

```toml
# engine=sdk on the Claude subscription (lands in M3). P4 guards apply now.
engine = "sdk"
sandbox = "gvisor"

[roles.main]
model = "claude-sonnet-5-5"
```

`config/profiles/prod.toml`:

```toml
engine = "own"
sandbox = "gvisor"
bind = "0.0.0.0"
multi_user = true

[roles.main]
model = "claude-sonnet-5-5"
api_key_env = "ANTHROPIC_API_KEY"
max_output_tokens = 16000
effort = "medium"

[roles.light]
model = "claude-haiku-4-5"
api_key_env = "ANTHROPIC_API_KEY"
max_output_tokens = 4096
```

- [ ] **Step 2: Write the failing tests.** Create an empty `tests/app/__init__.py`. Then `tests/app/test_guards.py`:

```python
from pathlib import Path

import pytest

from usta.app.config import Profile, RoleConfig, load_profile
from usta.app.guards import validate_startup
from usta.core.errors import ConfigError
from usta.models.caps import ModelEntry, load_catalog

CONFIG = Path("config")
CATALOG = load_catalog(CONFIG / "models.toml")


@pytest.mark.parametrize(
    ("name", "env"),
    [
        ("test", {}),
        ("dev-free", {"GEMINI_API_KEY": "k"}),
        ("dev-api", {"ANTHROPIC_API_KEY": "k"}),
        ("dev-sub", {}),
        ("prod", {"ANTHROPIC_API_KEY": "k"}),
    ],
)
def test_shipped_profiles_pass_their_guards(name: str, env: dict) -> None:
    validate_startup(load_profile(name, CONFIG), CATALOG, env)


def test_dev_sub_refuses_an_api_key_p4() -> None:
    with pytest.raises(ConfigError, match="P4.*ANTHROPIC_API_KEY"):
        validate_startup(load_profile("dev-sub", CONFIG), CATALOG, {"ANTHROPIC_API_KEY": "sk"})


def test_fake_model_and_docker_hardened_only_in_test_p8() -> None:
    p = load_profile("test", CONFIG).model_copy(update={"name": "dev-free"})
    with pytest.raises(ConfigError) as info:
        validate_startup(p, CATALOG, {})
    assert "docker_hardened" in str(info.value) and "fake model" in str(info.value)


def test_missing_catalog_entry_and_missing_key_are_listed_together() -> None:
    p = load_profile("dev-free", CONFIG)
    p = p.model_copy(update={"roles": {**p.roles, "light": RoleConfig(model="unknown/model")}})
    with pytest.raises(ConfigError) as info:
        validate_startup(p, CATALOG, {})
    assert "P7" in str(info.value) and "GEMINI_API_KEY" in str(info.value)


def test_model_without_native_tools_is_refused() -> None:
    no_tools = CATALOG["fake-model"].model_copy(update={"native_tools": False})
    catalog: dict[str, ModelEntry] = {**CATALOG, "fake-model": no_tools}
    with pytest.raises(ConfigError, match="native tool"):
        validate_startup(load_profile("test", CONFIG), catalog, {})


def test_single_user_profile_must_bind_loopback() -> None:
    p = load_profile("dev-free", CONFIG).model_copy(update={"bind": "0.0.0.0"})
    with pytest.raises(ConfigError, match="127.0.0.1"):
        validate_startup(p, CATALOG, {"GEMINI_API_KEY": "k"})


def test_unknown_profile_and_typos_fail_loudly(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown profile"):
        load_profile("nope", CONFIG)
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "x.toml").write_text(
        'engine = "own"\nsandbox = "gvisor"\nsandbx = "typo"\n[roles.main]\nmodel = "fake-model"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="sandbx"):
        load_profile("x", tmp_path)


def test_profile_without_main_role_is_refused() -> None:
    p = Profile(name="t", engine="own", sandbox="gvisor", roles={"light": RoleConfig(model="fake-model")})
    with pytest.raises(ConfigError, match="main role"):
        validate_startup(p, CATALOG, {})
```

`tests/app/test_wiring.py`:

```python
from pathlib import Path

import pytest
from sqlalchemy import text

from usta.app.config import Settings
from usta.app.wiring import build_app
from usta.core.errors import ConfigError
from usta.core.run import StopReason
from usta.models.fake import FakeModel, call, reply

TODO_ITEMS = [
    {"content": "Hesabatı yoxla", "status": "pending"},
    {"content": "Müştəriyə zəng et", "status": "pending"},
]


@pytest.mark.pg
async def test_two_tool_task_runs_end_to_end_through_real_wiring(clean_db: str, tmp_path: Path) -> None:
    files = tmp_path / "u1" / "files"
    files.mkdir(parents=True)
    (files / "qeydler.txt").write_text("1. Hesabatı yoxla\n2. Müştəriyə zəng et\n", encoding="utf-8")
    script = [
        call("file.read", {"path": "files/qeydler.txt"}),
        call("todo", {"items": TODO_ITEMS}),
        reply("İki tapşırıq tapdım və siyahıya saldım."),
    ]
    settings = Settings(profile="test", database_url=clean_db, workspace_root=tmp_path)
    app = await build_app(settings, env={}, model_overrides={"main": FakeModel(script)})
    try:
        await app.store.add_user("u1", "Test")
        run = await app.worker.execute((await app.worker.submit("u1", "Qeydləri oxu və siyahı qur")).id)
        assert run.stop_reason == StopReason.DONE
        assert [t.content for t in run.todo] == ["Hesabatı yoxla", "Müştəriyə zəng et"]
        async with app.db.connect() as conn:
            n_calls = (await conn.execute(text("SELECT count(*) FROM model_calls WHERE run_id = :r"), {"r": run.id})).scalar_one()
            tools = (await conn.execute(text("SELECT tool, phase FROM tool_calls WHERE run_id = :r ORDER BY created_at"), {"r": run.id})).all()
            n_events = (await conn.execute(text("SELECT count(*) FROM run_events WHERE run_id = :r"), {"r": run.id})).scalar_one()
        assert n_calls == 3
        assert [tuple(t) for t in tools] == [
            ("file.read", "intent"), ("file.read", "done"), ("todo", "intent"), ("todo", "done"),
        ]
        assert n_events >= 9
    finally:
        await app.aclose()


async def test_model_overrides_are_refused_outside_the_test_profile() -> None:
    settings = Settings(profile="dev-free", database_url="postgresql+asyncpg://x@127.0.0.1/x")
    with pytest.raises(ConfigError, match="P8"):
        await build_app(settings, env={"GEMINI_API_KEY": "k"}, model_overrides={"main": FakeModel()})


async def test_sdk_engine_is_not_wired_before_m3() -> None:
    settings = Settings(profile="dev-sub", database_url="postgresql+asyncpg://x@127.0.0.1/x")
    with pytest.raises(ConfigError, match="M3"):
        await build_app(settings, env={})
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/app -q`
Expected: `ModuleNotFoundError: No module named 'usta.app.config'`.

- [ ] **Step 4: Implement.** `usta/app/config.py`:

```python
"""Settings from the environment and named profiles from config/profiles/*.toml (SPEC §5.1)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from usta.core.errors import ConfigError
from usta.core.model import Role


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USTA_", extra="ignore")

    profile: str
    database_url: str
    user: str = ""
    config_dir: Path = Path("config")
    workspace_root: Path = Path("workspaces")


class RoleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    api_key_env: str | None = None
    api_base: str | None = None
    max_output_tokens: int = 8192
    effort: str | None = None


class BudgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_turns: int = 40
    cost_cap_usd: float = 0.50
    max_active_seconds: float = 1200.0
    user_monthly_cap_usd: float = 10.0


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    engine: Literal["own", "sdk"]
    sandbox: Literal["gvisor", "docker_hardened"]
    bind: str = "127.0.0.1"
    multi_user: bool = False
    roles: dict[Role, RoleConfig]
    budget: BudgetConfig = Field(default_factory=BudgetConfig)


def load_profile(name: str, config_dir: Path) -> Profile:
    path = config_dir / "profiles" / f"{name}.toml"
    if not path.is_file():
        raise ConfigError(f"unknown profile {name!r}: {path} not found")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    try:
        return Profile.model_validate({"name": name, **data})
    except ValidationError as e:
        raise ConfigError(f"{path}: {e}") from e
```

`usta/app/guards.py`:

```python
"""Startup guards (SPEC §5.1): P4, P7, P8, ADR-021. Every problem is listed, then startup stops."""

from collections.abc import Mapping

from usta.app.config import Profile
from usta.core.errors import ConfigError
from usta.models.caps import ModelEntry


def validate_startup(
    profile: Profile, catalog: Mapping[str, ModelEntry], env: Mapping[str, str]
) -> None:
    problems: list[str] = []
    is_test = profile.name == "test"

    if "main" not in profile.roles:
        problems.append("profile has no main role")
    if not is_test and profile.sandbox == "docker_hardened":
        problems.append("P8: the docker_hardened sandbox is allowed only in the test profile")
    if not profile.multi_user and profile.bind != "127.0.0.1":
        problems.append(f"single-user profiles must bind 127.0.0.1, not {profile.bind}")
    if profile.name == "dev-sub":
        if env.get("ANTHROPIC_API_KEY"):
            problems.append(
                "P4: dev-sub runs on the Claude subscription; unset ANTHROPIC_API_KEY "
                "(it would override the subscription login)"
            )
        if profile.multi_user:
            problems.append("P4: dev-sub is single-user only")

    for role, rc in profile.roles.items():
        entry = catalog.get(rc.model)
        if entry is None:
            problems.append(
                f"P7: role {role}: model {rc.model!r} has no entry (caps + price) in models.toml"
            )
            continue
        if not entry.native_tools:
            problems.append(f"ADR-021: role {role}: model {rc.model!r} has no native tool calling")
        if entry.adapter == "fake" and not is_test:
            problems.append(f"P8: role {role}: the fake model is allowed only in the test profile")
    for role, rc in profile.roles.items():
        if rc.api_key_env and not env.get(rc.api_key_env):
            problems.append(f"role {role}: environment variable {rc.api_key_env} is not set")

    if problems:
        raise ConfigError("startup refused:\n- " + "\n- ".join(problems))
```

`usta/app/wiring.py`:

```python
"""Composition root: the only module that knows concrete adapters (P5)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from usta.app.config import Profile, RoleConfig, Settings, load_profile
from usta.app.guards import validate_startup
from usta.core.budget import Budget
from usta.core.errors import ConfigError
from usta.core.model import Role
from usta.engines.own.loop import OwnEngine
from usta.models.caps import ModelEntry, load_catalog
from usta.models.fake import FakeModel
from usta.models.gateway import Gateway
from usta.ports import ModelPort, RunContext
from usta.store.pg import PgRunStore
from usta.tools.builtin import builtin_tools
from usta.tools.pipeline import ToolPipeline
from usta.tools.registry import ToolRegistry
from usta.worker import EventCallback, Worker


@dataclass
class App:
    profile: Profile
    db: AsyncEngine
    store: PgRunStore
    worker: Worker

    async def aclose(self) -> None:
        await self.db.dispose()


def build_model(
    model_id: str, entry: ModelEntry, rc: RoleConfig, env: Mapping[str, str]
) -> ModelPort:
    key = env.get(rc.api_key_env) if rc.api_key_env else None
    if entry.adapter == "anthropic":
        from usta.models.anthropic_adapter import AnthropicModel

        return AnthropicModel(
            model_id, entry.caps, api_key=key or "", max_output_tokens=rc.max_output_tokens, effort=rc.effort
        )
    if entry.adapter == "litellm":
        from usta.models.litellm_adapter import LiteLLMModel  # litellm loads only when used

        return LiteLLMModel(
            model_id,
            entry.caps,
            api_key=key,
            max_output_tokens=rc.max_output_tokens,
            api_base=rc.api_base,
            effort=rc.effort,
        )
    return FakeModel(model_id=model_id, caps=entry.caps)  # guards allow this only in `test`


async def build_app(
    settings: Settings,
    *,
    env: Mapping[str, str] = os.environ,
    model_overrides: Mapping[Role, ModelPort] | None = None,
    on_event: EventCallback | None = None,
) -> App:
    profile = load_profile(settings.profile, settings.config_dir)
    catalog = load_catalog(settings.config_dir / "models.toml")
    validate_startup(profile, catalog, env)
    if profile.engine != "own":
        raise ConfigError("engine=sdk arrives in M3; use an engine=own profile")
    if model_overrides and profile.name != "test":
        raise ConfigError("P8: model overrides are allowed only in the test profile")

    overrides = model_overrides or {}
    models: dict[Role, ModelPort] = {
        role: overrides.get(role) or build_model(rc.model, catalog[rc.model], rc, env)
        for role, rc in profile.roles.items()
    }
    unknown = sorted({m.model_id for m in models.values()} - catalog.keys())
    if unknown:
        raise ConfigError(f"P7: no catalog entry for {unknown}")

    db = create_async_engine(settings.database_url, pool_pre_ping=True)
    store = PgRunStore(db, profile=profile.name)
    gateway = Gateway(
        models, {m.model_id: catalog[m.model_id].price for m in models.values()}, audit=store
    )
    pipeline = ToolPipeline(
        ToolRegistry(builtin_tools()), audit=store, workspace_root=settings.workspace_root
    )
    b = profile.budget
    budget = Budget(
        max_turns=b.max_turns, cost_step_usd=b.cost_cap_usd, max_active_seconds=b.max_active_seconds
    )
    worker = Worker(
        store,
        OwnEngine(budget),
        RunContext(models=gateway, tools=pipeline, store=store),
        budget,
        engine_name="own",
        user_monthly_cap_usd=b.user_monthly_cap_usd,
        on_event=on_event,
    )
    return App(profile=profile, db=db, store=store, worker=worker)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/app -q && uv run lint-imports`
Expected: all pass. The contracts are kept: `usta.app` imports the adapters, and nothing below it does.

- [ ] **Step 6: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add config/profiles usta/app tests/app
git commit -m "feat(app): profiles, startup guards (P4/P7/P8) and composition root"
```

---

### Task 14: CLI (`usta run | answer | cancel | recover | user`)

**Files:**
- Modify: `usta/cli.py`, `pyproject.toml` (add `[project.scripts]`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Settings`, `build_app`, `App`, `Event`, `RunState`, `StopReason`, `UstaError`.
- Produces:
  - `build_parser() -> argparse.ArgumentParser`
  - `format_event(ev: Event) -> str`
  - `main(argv: list[str] | None = None, *, app_factory=build_app) -> int`

  Exit codes: `0` = done or OK, `1` = finished with another stop reason, `2` = usage or config error (message only, no traceback), `3` = parked.

- [ ] **Step 1: Write the failing test** `tests/test_cli.py`:

```python
import functools
from pathlib import Path

import pytest

from usta.app.wiring import build_app
from usta.cli import build_parser, format_event, main
from usta.core.events import Event
from usta.models.fake import FakeModel, call, reply


def test_parser_commands() -> None:
    p = build_parser()
    assert p.parse_args(["run", "Hesabat hazırla"]).task == "Hesabat hazırla"
    assert p.parse_args(["answer", "r1", "yes"]).decision == "yes"
    with pytest.raises(SystemExit):
        p.parse_args(["answer", "r1", "maybe"])
    assert p.parse_args(["user", "fariz", "--scope", "fleet:read"]).scope == ["fleet:read"]


def test_format_event_keeps_azerbaijani_readable() -> None:
    ev = Event(run_id="r1", type="tool_call", data={"call_id": "c", "name": "file.read", "input": {"path": "files/qeydlər.txt"}})
    assert format_event(ev) == '  → file.read {"path": "files/qeydlər.txt"}'
    fin = Event(run_id="r1", type="finished", data={"stop_reason": "done", "detail": None, "turns": 2, "cost_usd": 0.0012})
    assert format_event(fin) == "■ done · 2 turns · $0.0012"


def test_missing_settings_are_a_clean_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.delenv("USTA_PROFILE", raising=False)
    assert main(["recover"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("usta: ") and "profile" in err and "Traceback" not in err


@pytest.mark.pg
def test_cli_runs_a_task_end_to_end(clean_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv("USTA_PROFILE", "test")
    monkeypatch.setenv("USTA_DATABASE_URL", clean_db)
    monkeypatch.setenv("USTA_USER", "u1")
    monkeypatch.setenv("USTA_WORKSPACE_ROOT", str(tmp_path))
    script = [call("todo", {"items": [{"content": "Siyahı qur", "status": "done"}]}), reply("Hazırdır, ə ğ ı ş.")]
    factory = functools.partial(build_app, model_overrides={"main": FakeModel(script)})

    assert main(["user", "u1", "--name", "Test"], app_factory=factory) == 0
    assert main(["run", "Siyahı qur"], app_factory=factory) == 0
    out = capsys.readouterr().out
    assert "→ todo" in out and "■ done" in out
    assert out.rstrip().endswith("Hazırdır, ə ğ ı ş.")


@pytest.mark.pg
def test_unknown_user_is_a_clean_error(clean_db: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv("USTA_PROFILE", "test")
    monkeypatch.setenv("USTA_DATABASE_URL", clean_db)
    monkeypatch.setenv("USTA_USER", "ghost")
    factory = functools.partial(build_app, model_overrides={"main": FakeModel([])})
    assert main(["run", "salam"], app_factory=factory) == 2
    assert "usta user ghost" in capsys.readouterr().err
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_cli.py -q`
Expected: `ImportError: cannot import name 'build_parser' from 'usta.cli'`.

- [ ] **Step 3: Implement** `usta/cli.py`:

```python
"""Usta command line (SPEC §14). Same composition root as the API."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from usta.app.config import Settings
from usta.app.wiring import App, build_app
from usta.core.errors import UstaError
from usta.core.events import Event
from usta.core.run import RunState, StopReason

AppFactory = Callable[..., Awaitable[App]]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="usta", description="Usta work agent")
    sub = p.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run a task as $USTA_USER")
    run.add_argument("task")
    answer = sub.add_parser("answer", help="answer a run parked on its budget")
    answer.add_argument("run_id")
    answer.add_argument("decision", choices=["yes", "no"])
    cancel = sub.add_parser("cancel", help="cancel a run")
    cancel.add_argument("run_id")
    sub.add_parser("recover", help="resume runs a crash left running or queued")
    user = sub.add_parser("user", help="add or update a user")
    user.add_argument("user_id")
    user.add_argument("--name")
    user.add_argument("--scope", action="append", default=[])
    return p


def format_event(ev: Event) -> str:
    d = ev.data
    match ev.type:
        case "run_started":
            return f"▶ run {ev.run_id}"
        case "model_call":
            return f"[turn {d['turn']}] {d['model']} · {d['stop']} · ${d['cost_usd']:.4f}"
        case "tool_call":
            return f"  → {d['name']} {json.dumps(d['input'], ensure_ascii=False)}"
        case "tool_result":
            status = "error" if d["is_error"] else "ok"
            return f"  ← {d['name']}: {status} ({d['chars']} chars)"
        case "todo_updated":
            return "  ☐ " + " | ".join(f"[{i['status']}] {i['content']}" for i in d["items"])
        case "step_done":
            return f"  · ${d['cost_usd']:.4f} so far"
        case "parked":
            question = (d.get("question") or {}).get("text", "")
            return f"⏸ {d['status']}: {question}  (usta answer {ev.run_id} yes|no)"
        case "finished":
            detail = f": {d['detail']}" if d.get("detail") else ""
            return f"■ {d['stop_reason']}{detail} · {d['turns']} turns · ${d['cost_usd']:.4f}"
    return f"{ev.type} {json.dumps(d, ensure_ascii=False)}"


async def _print_event(ev: Event) -> None:
    print(format_event(ev), flush=True)


def _exit_code(run: RunState) -> int:
    if run.is_parked:
        return 3
    if run.is_finished and run.stop_reason != StopReason.DONE:
        return 1
    if run.is_finished:
        print("\n" + run.final_text())
    return 0


async def _main(args: argparse.Namespace, settings: Settings, app_factory: AppFactory) -> int:
    if args.command == "run" and not settings.user:
        raise UstaError("set USTA_USER to the user id that runs tasks (see `usta user`)")
    app = await app_factory(settings, on_event=_print_event)
    try:
        match args.command:
            case "user":
                await app.store.add_user(args.user_id, args.name or args.user_id, args.scope)
                print(f"user {args.user_id} saved")
                return 0
            case "recover":
                ids = await app.worker.recover()
                print(f"recovered {len(ids)} run(s)")
                return 0
            case "run":
                run = await app.worker.submit(settings.user, args.task)
                run = await app.worker.execute(run.id)
            case "answer":
                run = await app.worker.answer_budget(args.run_id, args.decision == "yes")
            case "cancel":
                run = await app.worker.cancel(args.run_id)
            case _:
                raise UstaError(f"unknown command {args.command}")
        return _exit_code(run)
    finally:
        await app.aclose()


def main(argv: list[str] | None = None, *, app_factory: AppFactory = build_app) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        settings = Settings()
        return asyncio.run(_main(args, settings, app_factory))
    except (UstaError, ValidationError, ValueError, KeyError) as e:  # e.g. unknown run id
        print(f"usta: {e}", file=sys.stderr)
        return 2
```

In `pyproject.toml`, under `[project]`, add:

```toml
[project.scripts]
usta = "usta.cli:main"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv sync && uv run pytest tests/test_cli.py -q && uv run usta --help`
Expected: `5 passed`, and the help text lists `run, answer, cancel, recover, user`.

- [ ] **Step 5: Full T1 suite and contracts**

Run: `uv run ruff format --check . && uv run ruff check . && uv run lint-imports && uv run pytest -q --tb=short`
Expected: everything is green. Note the total test count for the M0 evidence report.

- [ ] **Step 6: Commit and push**

```bash
uv run ruff check --fix . && uv run ruff format .
git add usta/cli.py pyproject.toml uv.lock tests/test_cli.py
git commit -m "feat(cli): usta run/answer/cancel/recover/user with explicit exit codes"
git push
```

Confirm that both CI jobs (`gitleaks`, `t1`) are green on GitHub. This is the first half of the M0 proof.

---

### Task 15: `dev-free` smoke: the M0 proof of done

**Files:**
- Create: `tests/models/test_litellm_live.py` (marked `live`; not in CI)
- Modify (only if the model changes): `config/models.toml`, `config/profiles/dev-free.toml`
- Modify: `SPEC.md` §20 item 2, `docs/adr/ADR-013-dev-model-access.md` (record the chosen free-tier model)

**Interfaces:**
- Consumes: `load_profile`, `load_catalog`, `LiteLLMModel`, and the CLI.

- [ ] **Step 1: Pick the free-tier model (SPEC §20 item 2).** The default is `gemini/gemini-2.5-flash` on a Google AI Studio free key. Check that it is still free-tier with native tool calling, and that the catalog's caps and list prices still match the provider's pricing page. If it isn't, choose the best free-tier tool-calling model available through LiteLLM, then update the `config/models.toml` entry and both roles in `config/profiles/dev-free.toml` (and the expected IDs in `tests/models/test_catalog.py`). Put the key in `.env` as `GEMINI_API_KEY`, or whichever variable the profile names. Never commit it.

- [ ] **Step 2: Write the live test** `tests/models/test_litellm_live.py`:

```python
"""Live check of the dev-free model: tool call + tool-result round trip. Run: pytest -m live"""

import os
from pathlib import Path

import pytest

from usta.app.config import load_profile
from usta.core.messages import Message, ToolResult
from usta.core.model import ModelRequest, SystemBlock
from usta.models.caps import load_catalog
from usta.models.litellm_adapter import LiteLLMModel
from tests.models.contract import READ_SPEC

pytestmark = pytest.mark.live


async def test_free_tier_model_calls_a_tool_and_accepts_the_result() -> None:
    rc = load_profile("dev-free", Path("config")).roles["main"]
    key = os.environ.get(rc.api_key_env or "")
    assert key, f"{rc.api_key_env} must be set for live tests"
    entry = load_catalog(Path("config/models.toml"))[rc.model]
    model = LiteLLMModel(rc.model, entry.caps, api_key=key, max_output_tokens=1024)
    req = ModelRequest(
        role="main",
        system=(SystemBlock(text="Use the file.read tool to read files before answering.", cache=True),),
        messages=(Message.user_text("files/qeyd.txt faylını oxu və nə yazıldığını de."),),
        tools=(READ_SPEC,),
        prompt_version="live-v1",
    )
    first = await model.complete(req)
    [call] = first.tool_calls()
    assert call.name == "file.read" and call.input.get("path") and call.input_error is None
    assert first.usage.output_tokens > 0

    follow = req.model_copy(
        update={
            "messages": req.messages
            + (first.message, Message(role="user", content=(ToolResult(call_id=call.id, content="Sabah saat 10-da iclas var."),)))
        }
    )
    second = await model.complete(follow)
    assert second.message.text().strip()
    assert second.tool_calls() == []
```

- [ ] **Step 3: Run it**

Run: `set -a; source .env; set +a; uv run pytest -m live tests/models/test_litellm_live.py -q`
Expected: `1 passed`. If the second call fails with a provider error about missing thought or function-call signatures, the adapter must preserve the provider-specific fields as `OpaqueBlock`s. Fix the adapter with a unit test first (red/green), then re-run this test. Do not switch to text-emulated tools (ADR-021).

- [ ] **Step 4: Run the 2-tool task through the real CLI on `dev-free`**

```bash
set -a; source .env; set +a                     # USTA_PROFILE=dev-free, USTA_USER=fariz
docker compose -f deploy/compose.dev.yml up -d
uv run alembic upgrade head
uv run usta user fariz --name "Fariz"
mkdir -p workspaces/fariz/files
printf 'Həftəlik qeydlər\n1. Yanacaq hesabatını yoxla\n2. FMC130 qiymətini soruş\n3. Müştəri şikayətinə cavab yaz\n' > workspaces/fariz/files/qeydler.txt
uv run usta run "files/qeydler.txt faylını oxu, tapşırıqlardan todo siyahısı qur və qısa xülasə yaz."
```

Expected:
- `→ file.read {"path": "files/qeydler.txt"}`, then `→ todo {...}` with 3 items
- `■ done · N turns · $0.00xx`
- an Azerbaijani summary
- exit code 0

Check the audit trail: `docker compose -f deploy/compose.dev.yml exec postgres psql -U usta -d usta -c "select model, attempt, input_tokens, output_tokens, cost_usd, error from model_calls order by created_at desc limit 5;"`. It should show one row per model call, with token counts and cost, and no errors.

If the free model fails for model reasons (it skips tools, loops, or replies in the wrong language), record it. That is the "free-tier model too weak" risk in SPEC §18, and the mitigation there is a short `dev-api` session. Don't change the harness to paper over model quality.

- [ ] **Step 5: Record and commit.** Append the chosen model and date to SPEC §20 item 2, and add a "Chosen free-tier model" line to ADR-013. Save the smoke transcript (CLI output plus the psql rows) to `docs/milestones/m0-smoke.md` with today's date. It must contain no keys.

```bash
git add tests/models/test_litellm_live.py config SPEC.md docs/adr/ADR-013-dev-model-access.md docs/milestones/m0-smoke.md
git commit -m "test(m0): dev-free live check and 2-tool smoke; record free-tier model"
git push
git tag m0 && git push origin m0
```

---

## M0 Done Criteria (SPEC §16)

- [ ] CI is green on GitHub (gitleaks; ruff; lint-imports with 3 contracts; the full T1 pytest suite against Postgres).
- [ ] The `dev-free` 2-tool task completes via `usta run` with `stop_reason=done`, and its audit rows are present (Task 15, Step 4).
- [ ] The gVisor spike result is recorded in ADR-005 and SPEC §20.
- [ ] Evidence report: the files changed, the commands run, the test count, the CI link, and the smoke transcript. Known limitations are listed below.

## Known Limitations Carried Out of M0

- No verdict, taint or approvals yet (M2). `file.read` is unrestricted inside the user's workspace.
- No context management (M3). Long runs can overflow the model window, and `file.read` truncates at 50k characters.
- Tools run sequentially, even when `caps.parallel_tool_calls` is true.
- `ModelCallRecord.request` stores the full history on every call, so audit size grows quadratically with turns. Revisit storage in M3 (e.g. store per-turn deltas).
- `Settings.config_dir` is relative, so the CLI must run from the repo root.
- The monthly user cap only refuses new runs. A run in progress stops at its own per-run cap.
- Run exclusion is in-process only (Worker guard, Task 10). Two `usta` processes resuming the same run fail loudly on the `run_checkpoints` PK rather than being prevented; a lease (`lease_owner` / `lease_until`) is a later additive migration.
- gVisor in WSL2 works only on runsc platforms `kvm`/`ptrace` (default `systrap` fails; ADR-005). The production VM's platform is checked at VM setup. M0 uses no sandbox.
- LiteLLM adapter: provider-specific fields such as Gemini thought signatures are not preserved unless Task 15 forces it.
- ⚠️ Preserved-thinking enforcement on Sonnet/Opus 5.5 conflicts with history-editing context layers. Revisit ADR-017 before M3 (Plan Decision 5).

