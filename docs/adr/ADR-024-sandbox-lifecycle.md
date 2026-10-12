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

## Implementation (M1)
- Driver: the Docker CLI (`docker run/exec/rm/ps`) through asyncio subprocesses, one container per run (`usta/sandbox/docker.py`).
- Timeouts: each exec runs under an inner `timeout --kill-after=2 <secs>`; an outer wait of the timeout plus 10 s catches a wedged runtime, and on expiry the container is destroyed.
- Naming and lifecycle: containers are named `usta-sbx-<run_id>` and labelled `usta.run=<run_id>`. The worker releases the container when a run parks or finishes; on recover it reaps labelled containers whose run is not active.
- Identity: the container runs as the host uid:gid. The image sets `HOME=/tmp` and `MPLCONFIGDIR=/tmp/matplotlib` (tmpfs, 256 MB), since the root filesystem is read-only.
- Output cap: `/out` is limited to 200 MB, checked after each call (not within one call). Streams are read up to 256 KB and cut to 5,000 characters per stream in `code_exec`.
- Process limits: the guest cap is `--ulimit nproc=128:128` (RLIMIT_NPROC, enforced by gVisor's sentry on both platforms). `--pids-limit 4096` is only a host backstop: under gVisor ptrace/systrap each guest process costs about 8-10 host threads, and under runsc-kvm the host pids cgroup does not see guest processes at all (measured: 300 processes started under `--pids-limit 128`).
- Timeout recovery: an exec that ends with exit 124 or 137 destroys the container, because stray children could hold the nproc budget. The next exec recreates it; `/out` survives, `/tmp` and background jobs do not. The per-run exec lock is kept across the destroy.
- Gone container: an exec that finds the container gone or stopped (the daemon's "Error response from daemon" on stderr, or the runtime's "OCI runtime exec failed", which docker relays on stdout) recreates it once. Seen in CI when a memory bomb took the sentry down under systrap.
- gVisor quirk: a single stdout write over 64 KiB through `docker exec` is silently cut to 65536 bytes with exit 0, and the `truncated` flag is not set. Programs should write in smaller chunks; the 5,000-character output cap makes this moot for results the model sees.
