# Usta sandbox image (SPEC §10, ADR-024). Built by scripts/build_sandbox_image.sh; no registry
# before M5. Runs with --network=none, read-only root, non-root uid, no env vars from the host.
FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f

RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-noto-core \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

# The root fs is read-only at run time; /tmp is a tmpfs that lives as long as the run's
# container, so matplotlib builds its font cache once per run there.
ENV HOME=/tmp MPLCONFIGDIR=/tmp/matplotlib PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_INDEX=1
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin sandbox
USER 10001
WORKDIR /out
CMD ["sleep", "infinity"]
