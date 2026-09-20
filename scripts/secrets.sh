#!/usr/bin/env bash
# Creates the Secrets that cannot come from git. Values go
# env/file -> kubectl stdin -> cluster.
#
#   flux-system/sops-age   SOPS_AGE_KEY, the age key Flux decrypts
#                          releases/secrets/ with (bootstrap/flux.tf). Required.
#   kagent/kagent-openai   OPENAI_API_KEY, read by every OpenAI ModelConfig.
#                          Required.
#   kagent/kagent-gemini   GEMINI_API_KEY, read by the Gemini ModelConfig.
#                          Optional: without it only that ModelConfig is dead.
#   ngrok-operator/ngrok-operator-credentials
#                          NGROK_API_KEY and NGROK_AUTHTOKEN, one Secret with
#                          the keys API_KEY and AUTHTOKEN. Required: without it
#                          the ngrok-operator HelmRelease (retries: -1) never
#                          goes Ready, and the releases Kustomization waits on
#                          it, so the whole bundle would sit at Ready=False.
#
# Provider keys stay env-only: they already live in one durable place (a
# Codespaces Secret, or ~/.zshrc.local locally) and a copy in git would only
# make rotation a release. SOPS is for what has no such home -- today the
# xray-memory snapshot identity, releases/secrets/xray-memory-snapshot-key.yaml.
#
# releases/kagent.yaml deliberately gives the chart no apiKey, so the chart
# only references kagent-openai and a Helm upgrade never overwrites it.
#
# Every Secret is attempted; the exit code is non-zero if a required one could
# not be ensured, so `make run` stops here instead of waiting 20 minutes for a
# release that cannot become ready. Safe to re-run: values are replaced and
# nothing restarts; agents pick a changed key up on their next rollout.
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

# put_secret <namespace> <name> <data key> <value>
# stdin, not --from-literal: argv is readable by other processes.
put_secret() {
  printf '%s' "$4" \
    | kubectl -n "$1" create secret generic "$2" --from-file="$3"=/dev/stdin --dry-run=client -o yaml \
    | kubectl apply -f - >/dev/null
}

# env_secret <namespace> <secret name> <env var, also the data key> <required|optional>
env_secret() {
  local namespace="$1" name="$2" var="$3" need="$4"
  ensure_namespace "${namespace}" || return 1
  if [[ -n "${!var:-}" ]]; then
    put_secret "${namespace}" "${name}" "${var}" "${!var}" || return 1
    log "Secret ${namespace}/${name} set from ${var}"
    return 0
  fi
  secret_state "${namespace}" "${name}"
  case $? in
    0) log "${var} is not set, existing Secret ${namespace}/${name} kept"; return 0 ;;
    1) ;;
    *) log "ERROR: could not read Secret ${namespace}/${name}"; return 1 ;;
  esac
  if [[ "${need}" == optional ]]; then
    log "WARNING: ${var} is not set -- no Secret ${namespace}/${name}, whatever reads it will not work"
    return 0
  fi
  log "ERROR: ${var} is not set and there is no Secret ${namespace}/${name}"
  return 1
}

# The key comes from SOPS_AGE_KEY or from sops' own key file -- both are where
# `sops` itself looks, so whatever can edit the secrets can bootstrap the cluster.
sops_age_secret() {
  local key_file="${SOPS_AGE_KEY_FILE:-${HOME}/.config/sops/age/keys.txt}" key recipient
  if [[ -n "${SOPS_AGE_KEY:-}" ]]; then
    key="${SOPS_AGE_KEY}"
  elif [[ -f "${key_file}" ]]; then
    if ! key="$(grep '^AGE-SECRET-KEY-' "${key_file}")"; then
      log "ERROR: no AGE-SECRET-KEY line could be read from ${key_file}"
      return 1
    fi
  else
    secret_state flux-system sops-age
    case $? in
      0) log "SOPS_AGE_KEY is not set, existing Secret flux-system/sops-age kept"; return 0 ;;
      1) log "ERROR: no SOPS_AGE_KEY, no ${key_file} and no Secret flux-system/sops-age -- Flux cannot decrypt releases/secrets/" ;;
      *) log "ERROR: could not read Secret flux-system/sops-age" ;;
    esac
    return 1
  fi

  # Catch a pasted-wrong key here, not as a decryption failure in the cluster.
  if command -v age-keygen >/dev/null 2>&1; then
    if ! recipient="$(printf '%s\n' "${key}" | age-keygen -y 2>&1)"; then
      log "ERROR: the SOPS age key is not a valid age identity: ${recipient}"
      return 1
    fi
    if ! grep -qF "${recipient}" "$(dirname "$0")/../.sops.yaml"; then
      log "ERROR: the SOPS age key's recipient ${recipient} is not the one in .sops.yaml"
      return 1
    fi
  fi

  # kustomize-controller reads every *.agekey entry of the Secret as an identity.
  put_secret flux-system sops-age age.agekey "${key}"$'\n' || return 1
  log "Secret flux-system/sops-age set"
}

# Two keys in one Secret, so not env_secret. Both values or neither: half a
# credential would only move the failure into the operator's log.
ngrok_secret() {
  local namespace=ngrok-operator name=ngrok-operator-credentials
  ensure_namespace "${namespace}" || return 1
  if [[ -n "${NGROK_API_KEY:-}" && -n "${NGROK_AUTHTOKEN:-}" ]]; then
    # A generic Secret takes one --from-file per key; two stdin streams do not
    # exist, so the pair travels as an env file on stdin instead of in argv.
    printf 'API_KEY=%s\nAUTHTOKEN=%s\n' "${NGROK_API_KEY}" "${NGROK_AUTHTOKEN}" \
      | kubectl -n "${namespace}" create secret generic "${name}" \
          --from-env-file=/dev/stdin --dry-run=client -o yaml \
      | kubectl apply -f - >/dev/null || return 1
    log "Secret ${namespace}/${name} set from NGROK_API_KEY and NGROK_AUTHTOKEN"
    return 0
  fi
  secret_state "${namespace}" "${name}"
  case $? in
    0) log "NGROK_API_KEY/NGROK_AUTHTOKEN are not both set, existing Secret ${namespace}/${name} kept"; return 0 ;;
    1) log "ERROR: NGROK_API_KEY and NGROK_AUTHTOKEN must both be set and there is no Secret ${namespace}/${name}" ;;
    *) log "ERROR: could not read Secret ${namespace}/${name}" ;;
  esac
  return 1
}

rc=0
sops_age_secret || rc=1
env_secret kagent kagent-openai OPENAI_API_KEY required || rc=1
env_secret kagent kagent-gemini GEMINI_API_KEY optional || rc=1
ngrok_secret || rc=1
exit "${rc}"
