#!/usr/bin/env bash
# Build the sandbox image (SPEC §10). To change libraries: edit sandbox-image/requirements.in, then
#   uv pip compile sandbox-image/requirements.in --python-version 3.12 \
#     --python-platform x86_64-manylinux_2_28 --generate-hashes -o sandbox-image/requirements.txt
# To move the base image: update the FROM digest (docker inspect --format '{{index .RepoDigests 0}}').
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -t usta-sandbox:1 sandbox-image
