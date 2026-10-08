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
