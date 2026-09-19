#!/usr/bin/env bash
# Creates the hand-made Secrets the releases reference. Values go
# env/file -> kubectl stdin -> cluster and never touch git.
#
#   kagent-openai            OPENAI_API_KEY, the key every OpenAI ModelConfig
#                            reads -- locally exported in ~/.zshrc.local, on
#                            Codespaces a Codespaces Secret
#   xray-memory-snapshot-key the age identity xray-memory opens encrypted maps
#                            with; XRAY_SNAPSHOT_KEY, else a local key file,
#                            else generated
#
# The two are independent: both are attempted, and the exit code is non-zero
# if either one could not be ensured, so `make run` stops here instead of
# waiting 20 minutes for a release that cannot become ready.
#
# releases/kagent.yaml deliberately gives the chart no apiKey, so the chart
# only references this Secret and a Helm upgrade never overwrites it. Safe to
# re-run: kagent-openai is replaced and restarts nothing (agents pick a changed
# key up on their next rollout); xray-memory-snapshot-key is never replaced.
set -uo pipefail

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# The namespaces normally come from releases/*.yaml. Flux is already running
# when this does, so either side may create one first: apply is a no-op on a
# namespace that exists, where get-then-create races.
ensure_namespace() {
  kubectl create namespace "$1" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
}

# 0 the Secret exists, 1 it does not, 2 the API could not say (Forbidden,
# unreachable) -- which must not be read as "absent".
secret_state() {
  local out
  out="$(kubectl -n "$1" get secret "$2" --ignore-not-found -o name)" || return 2
  [[ -n "${out}" ]]
}

openai_secret() {
  ensure_namespace kagent || return 1
  if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    secret_state kagent kagent-openai
    case $? in
      0) log "OPENAI_API_KEY is not set, existing Secret kagent/kagent-openai kept"; return 0 ;;
      1) log "ERROR: OPENAI_API_KEY is not set and there is no Secret kagent-openai -- agent pods would sit in CreateContainerConfigError" ;;
      *) log "ERROR: could not read Secret kagent/kagent-openai" ;;
    esac
    return 1
  fi
  # stdin, not --from-literal: argv is readable by other processes.
  printf '%s' "${OPENAI_API_KEY}" \
    | kubectl -n kagent create secret generic kagent-openai \
        --from-file=OPENAI_API_KEY=/dev/stdin --dry-run=client -o yaml \
    | kubectl apply -f - >/dev/null || return 1
  log "Secret kagent/kagent-openai set from OPENAI_API_KEY"
}

# The identity reads encrypted maps; nothing is written encrypted unless
# releases/xray-memory.yaml also sets XRAY_SNAPSHOT_RECIPIENT, and it does not
# -- so today this key opens nothing of ours and only lets the pod mount its
# Secret volume (without it the kubelet retries the mount and the pod sits in
# ContainerCreating until the Secret appears). That is why a missing key is
# generated rather than asked for.
#
# An existing Secret is NEVER replaced. Swapping the identity is a rotation:
# once a recipient is set, everything on the claim is encrypted to the old key
# and a new one orphans it. Deleting the Secret re-encrypts nothing: to rotate,
# re-encrypt the maps first, then delete it and re-run. Setting
# XRAY_SNAPSHOT_KEY later does not touch an existing Secret either -- to pin
# the key in use, save THAT identity. Maps pushed to a registry outlive a generated key, so build those
# unencrypted or pin one key in XRAY_SNAPSHOT_KEY (the AGE-SECRET-KEY-1... line).
xray_secret() {
  local key_file="${HOME}/.config/xray-memory/snapshot.key" key recipient
  ensure_namespace xray-memory || return 1

  secret_state xray-memory xray-memory-snapshot-key
  case $? in
    0) log "Secret xray-memory/xray-memory-snapshot-key exists, kept as is"; return 0 ;;
    1) ;;
    *) log "ERROR: could not read Secret xray-memory/xray-memory-snapshot-key"; return 1 ;;
  esac
  # Only a NEW Secret needs age: to generate the identity or to validate one.
  if ! command -v age-keygen >/dev/null 2>&1; then
    log "ERROR: age-keygen not found (apt-get install age) -- cannot validate or generate the xray-memory identity"
    return 1
  fi

  if [[ -n "${XRAY_SNAPSHOT_KEY:-}" ]]; then
    key="${XRAY_SNAPSHOT_KEY}"
  else
    if [[ ! -f "${key_file}" ]]; then
      mkdir -p "$(dirname "${key_file}")" || return 1
      (umask 077 && age-keygen -o "${key_file}" >/dev/null) || return 1
      log "generated age identity ${key_file}"
    fi
    chmod 600 "${key_file}" || return 1
    if ! key="$(grep '^AGE-SECRET-KEY-' "${key_file}")"; then
      log "ERROR: no AGE-SECRET-KEY line could be read from ${key_file}"
      return 1
    fi
  fi

  if ! recipient="$(printf '%s\n' "${key}" | age-keygen -y 2>&1)"; then
    log "ERROR: the xray-memory identity is not a valid age key: ${recipient}"
    return 1
  fi
  # create, not apply: if the Secret appeared since the check, fail rather
  # than overwrite it.
  printf '%s\n' "${key}" \
    | kubectl -n xray-memory create secret generic xray-memory-snapshot-key \
        --from-file=identity=/dev/stdin >/dev/null || return 1
  log "Secret xray-memory/xray-memory-snapshot-key created, recipient ${recipient}"
}

rc=0
openai_secret || { log "ERROR: kagent-openai could not be ensured"; rc=1; }
xray_secret || { log "ERROR: xray-memory-snapshot-key could not be ensured"; rc=1; }
exit "${rc}"
