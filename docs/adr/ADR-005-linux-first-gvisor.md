# ADR-005: Linux-first hosting, gVisor everywhere   (resolves D-36, D-18 host)
Status: accepted (spike failed in WSL2: gVisor on VM only; dev/prod parity broken)
Date: 2026-10-07

## Context
The sandbox must be production-grade. gVisor and Firecracker need Linux; Firecracker also needs KVM. Dev machine: Windows 11 with WSL2 Ubuntu and Docker Desktop.

## Options considered
- A: WSL2 Ubuntu dev + one cloud Linux VM, gVisor in both. Against: VM cost; public demo needs login and caps.
- B: WSL2 only, video demo. Against: weaker production claim.
- C: Firecracker. Against: much more ops; nested KVM fragile.

## Decision
A. All code runs in Linux. `SandboxPort` has `gvisor` (default) and `docker_hardened` (test profile only). VM deployed at M5; cut to B if time runs out.

## Consequences
Day-1 spike: `runsc` in WSL2 + `--network=none`. Firecracker rejection is documented here.

## Revisit when
gVisor fails in WSL2 (then gVisor on VM only; dev/prod parity recorded as broken).

## Spike result (M0 day 1)
- Kernel: 6.6.114.1-microsoft-standard-WSL2; runsc: release-20260928.0
- hello: fail (`docker run --runtime=runsc python:3.12-slim` -> "OCI runtime start failed: ... urpc method containerManager.StartRoot failed: EOF"). --network=none and hardening flags: not reached (script stops at first failure).
- Notes: image pull works; the runsc sandbox process dies at start. Docker daemon has runsc registered with no extra flags (default platform systrap). Root cause not diagnosed (runsc debug logs need sudo). Next probe, to decide the platform before the VM fallback: `--platform=ptrace` in the runsc runtime args, then re-run `scripts/spike_gvisor.sh`.
