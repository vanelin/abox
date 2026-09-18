#!/usr/bin/env bash
# Creates the hand-made Secrets the releases reference, from environment
# variables -- locally exported in ~/.zshrc.local, on Codespaces a Codespaces
# Secret. The value goes env -> kubectl -> cluster and never touches a file
# or git.
#
#   kagent-openai / OPENAI_API_KEY   the key every OpenAI ModelConfig reads
#
# releases/kagent.yaml deliberately gives the chart no apiKey, so the chart
# only references this Secret and a Helm upgrade never overwrites it. Safe to
# re-run: it replaces the value and restarts nothing; agents pick a changed
# key up on their next rollout.
set -euo pipefail

log() { echo "[$(date '+%H:%M:%S')] $*"; }

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  log "WARNING: OPENAI_API_KEY is not set -- Secret kagent-openai not created, agents will fail with 401"
  exit 0
fi

# The namespace normally comes from releases/kagent.yaml; on a cold start this
# runs before Flux has reconciled it, and Flux adopts an existing one.
kubectl get namespace kagent >/dev/null 2>&1 || kubectl create namespace kagent >/dev/null

kubectl -n kagent create secret generic kagent-openai \
  --from-literal=OPENAI_API_KEY="${OPENAI_API_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
log "Secret kagent/kagent-openai set from OPENAI_API_KEY"
