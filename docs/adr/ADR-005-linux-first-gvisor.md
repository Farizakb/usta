# ADR-005: Linux-first hosting, gVisor everywhere   (resolves D-36, D-18 host)
Status: accepted (pending M0 spike)
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
