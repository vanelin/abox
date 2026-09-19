#!/usr/bin/env bash
# Hands Flux the one secret that cannot live in git: the age key that decrypts
# every other one. The Secrets the releases reference (kagent-openai,
# xray-memory-snapshot-key) are committed SOPS-encrypted under
# releases/secrets/, to the recipient in .sops.yaml; the releases Kustomization
# decrypts them with flux-system/sops-age (bootstrap/flux.tf).
#
# The key comes from SOPS_AGE_KEY -- on Codespaces a Codespaces Secret, locally
# exported in ~/.zshrc.local -- or from sops' own key file. Both are where
# `sops` itself looks, so whatever can edit the secrets can also bootstrap the
# cluster. The value goes env/file -> kubectl stdin -> cluster.
#
# Exits non-zero when Flux ends up without a key, so `make run` stops here
# instead of waiting 20 minutes for a Kustomization that cannot decrypt.
set -uo pipefail

log() { echo "[$(date '+%H:%M:%S')] $*"; }

KEY_FILE="${SOPS_AGE_KEY_FILE:-${HOME}/.config/sops/age/keys.txt}"

if [[ -n "${SOPS_AGE_KEY:-}" ]]; then
  key="${SOPS_AGE_KEY}"
elif [[ -f "${KEY_FILE}" ]]; then
  if ! key="$(grep '^AGE-SECRET-KEY-' "${KEY_FILE}")"; then
    log "ERROR: no AGE-SECRET-KEY line could be read from ${KEY_FILE}"
    exit 1
  fi
else
  # No source here is fine on a cluster that already has the key.
  if out="$(kubectl -n flux-system get secret sops-age --ignore-not-found -o name)" && [[ -n "${out}" ]]; then
    log "SOPS_AGE_KEY is not set, existing Secret flux-system/sops-age kept"
    exit 0
  fi
  log "ERROR: no SOPS_AGE_KEY, no ${KEY_FILE} and no Secret flux-system/sops-age -- Flux cannot decrypt releases/secrets/"
  exit 1
fi

# Catch a pasted-wrong key here, not as a decryption failure in the cluster.
if command -v age-keygen >/dev/null 2>&1; then
  if ! recipient="$(printf '%s\n' "${key}" | age-keygen -y 2>&1)"; then
    log "ERROR: the SOPS age key is not a valid age identity: ${recipient}"
    exit 1
  fi
  if ! grep -qF "${recipient}" "$(dirname "$0")/../.sops.yaml"; then
    log "ERROR: the SOPS age key's recipient ${recipient} is not the one in .sops.yaml"
    exit 1
  fi
fi

# kustomize-controller reads every *.agekey entry of the Secret as an identity.
# stdin, not --from-literal: argv is readable by other processes.
if ! printf '%s\n' "${key}" \
  | kubectl -n flux-system create secret generic sops-age \
      --from-file=age.agekey=/dev/stdin --dry-run=client -o yaml \
  | kubectl apply -f - >/dev/null; then
  log "ERROR: Secret flux-system/sops-age could not be applied"
  exit 1
fi
log "Secret flux-system/sops-age set"
