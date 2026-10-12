#!/usr/bin/env bash
# M1 proof (SPEC §16): T-c-style task on a real model; correct xlsx + PDF passing checks.
# Usage: scripts/m1_proof.sh [profile]   (default dev-openai). Loads .env without printing it.
set -euo pipefail
cd "$(dirname "$0")/.."
PROFILE="${1:-dev-openai}"
set -a; source .env; set +a
export USTA_PROFILE="$PROFILE" USTA_USER=m1proof
export USTA_GVISOR_RUNTIME="${USTA_GVISOR_RUNTIME:-runsc-kvm}"
TRUTH="$(mktemp -d)/ground_truth.json"
uv run usta user m1proof --name "M1 proof" || true  # already exists on a re-run
uv run python -m fixtures.generate "workspaces/m1proof/files" "$TRUTH"
TASK="Bu Excel faylındakı cihaz siyahısını (files/cihazlar.xlsx) anbar qalıqları ilə \
(files/anbar_qaliqlari.xlsx) müqayisə et və uyğunsuzluqları cədvəldə göstər. Cədvəli \
out/uygunsuzluqlar.xlsx faylına yaz və nəticəni PDF hesabat kimi də hazırla."
ID_FILE="$(mktemp)"
uv run usta run "$TASK" | tee /dev/stderr | grep -oE '▶ run [0-9a-f-]+' | awk '{print $3}' > "$ID_FILE"
RUN_ID="$(cat "$ID_FILE")"; rm -f "$ID_FILE"
OUT="workspaces/m1proof/runs/$RUN_ID/out"
ls -la "$OUT"
XLSX="$(find "$OUT" -name '*.xlsx' | head -n 1)"
uv run python -m evals.checks.tc "$XLSX" "$TRUTH"
echo "run: $RUN_ID  truth: $TRUTH"
