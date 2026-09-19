#!/usr/bin/env bash
# Lab 5, optional 5: build the upstream voice agent with our A2A patch, load it
# into kind, install its chart and forward port 8081. Outside Flux on purpose:
# the source is a private repository, so nothing is pushed to a registry.
#   bash docs/labs/05/scripts/voice.sh
# Needs GEMINI_API_KEY, and read access to den-vasyliev/voice-agent for the
# first run (the clone is kept under the gitignored .local/).
set -euo pipefail
LAB="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(git -C "${LAB}" rev-parse --show-toplevel)"
SRC="${ROOT}/.local/lab05/src/voice-agent"
COMMIT=37a515c498dde0ef665fdeb501cc772b68ca3a79
HOST="${CODESPACE_NAME:-localhost}-8081.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"

: "${GEMINI_API_KEY:?GEMINI_API_KEY is not set}"

if [[ ! -d "${SRC}" ]]; then
  mkdir -p "$(dirname "${SRC}")"
  gh repo clone den-vasyliev/voice-agent "${SRC}" -- -q
  git -C "${SRC}" checkout -q "${COMMIT}"
  git -C "${SRC}" apply "${LAB}/patches/voice-agent-artifacts.patch"
fi

docker build -q -t voice-agent:lab5 "${SRC}"
kind load docker-image voice-agent:lab5 --name abox

kubectl create namespace voice-agent --dry-run=client -o yaml | kubectl apply -f - >/dev/null
printf '%s' "${GEMINI_API_KEY}" \
  | kubectl -n voice-agent create secret generic voice-agent-gemini \
      --from-file=GEMINI_API_KEY=/dev/stdin --dry-run=client -o yaml \
  | kubectl apply -f - >/dev/null

# The Host check refuses a WebSocket upgrade from anything but loopback unless
# the forwarded Codespaces host is allowed.
helm upgrade --install voice-agent "${SRC}/charts/voice-agent" -n voice-agent \
  -f "${LAB}/voice/values.yaml" --set "agent.allowedHosts[0]=${HOST}" >/dev/null
kubectl -n voice-agent rollout restart deploy/voice-agent >/dev/null
kubectl -n voice-agent rollout status deploy/voice-agent --timeout=120s

pkill -f "port-forward svc/voice-agent" 2>/dev/null || true
kubectl -n voice-agent port-forward svc/voice-agent 8081:8081 >/dev/null 2>&1 &
sleep 3
kubectl -n voice-agent logs deploy/voice-agent --tail=5
echo "open: https://${HOST}"
