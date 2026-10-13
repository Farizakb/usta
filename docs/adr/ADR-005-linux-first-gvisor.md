# ADR-005: Linux-first hosting, gVisor everywhere   (resolves D-36, D-18 host)
Status: accepted (spike passed 2026-10-08 in WSL2 on runsc platforms kvm and ptrace; systrap fails)
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
- Kernel: 6.6.114.1-microsoft-standard-WSL2; runsc: release-20260928.0; Docker 29.8.2; cgroup v2.
- Platform `systrap` (runsc default): fail. Sandbox dies at start ("urpc method containerManager.StartRoot failed: EOF"), both via Docker and `runsc --rootless do`.
- Platform `ptrace`: hello / gVisor kernel / --network=none / hardening flags: pass (all four checks, `SPIKE PASSED`).
- Platform `kvm` (WSL2 exposes /dev/kvm via nested virtualization): all four checks pass (`RUNSC_RUNTIME=runsc-kvm ./scripts/spike_gvisor.sh`).
- Speed: container start ~0.6 s on both; a syscall-heavy loop (200k `getpid`) took 13.7 s on ptrace vs 1.1 s on kvm.
- Dev setup: `/etc/docker/daemon.json` registers `runsc` (`--platform=ptrace`) and `runsc-kvm` (`--platform=kvm`). The sandbox (M1) should default to `runsc-kvm` in dev, with `runsc` (ptrace) as the fallback.
- Production VM platform is not decided yet; it is checked when the VM is set up (systrap or kvm, depending on the VM's nested-virtualization support).

## Implementation (M1)
- Dev sets `USTA_GVISOR_RUNTIME=runsc-kvm`. CI uses `runsc` (systrap) on GitHub VMs, so the T3a suite runs on both platforms.
