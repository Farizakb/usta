# ADR-024: Sandbox lifecycle and hardening   (resolves D-18)
Status: accepted
Date: 2026-10-07

## Context
gVisor chosen (ADR-005). Need lifecycle, limits and image.

## Options considered
A container per call; B container per run, process per call, state in files; C persistent kernel.

## Decision
B. Container destroyed on park or finish, recreated on resume. Hardening: runsc, `--network=none`, cap-drop ALL, no-new-privileges, non-root, read-only root, tmpfs /tmp, mounts `/workspace` ro, `/out` rw, `/skills` ro, no env vars. Limits per call: 60 s, 1 CPU, 1 GB, 128 pids, capped output. Pre-built pinned image with pandas, openpyxl, matplotlib, reportlab, pdfplumber, python-docx, DejaVu/Noto fonts. Both engines use it (SDK Bash/Write disabled).

## Consequences
T3a escape tests: network incl. metadata IP, write to /workspace, host paths, fork/memory bomb, env secrets.

## Revisit when
Startup latency per run hurts UX (consider a warm pool).
