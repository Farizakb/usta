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
