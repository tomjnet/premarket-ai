#!/usr/bin/env bash
# Checks that Ollama on the GPU host is reachable from Ubuntu WSL and from Podman
# containers, and prints the OLLAMA_HOST_IP / OLLAMA_BASE_URL to put in .env.
# Usage: scripts/wsl/03_check-ollama.sh
set -uo pipefail

CURL_IMAGE="docker.io/curlimages/curl:latest"
PORT=11434
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
pass() { printf '  \033[32mOK\033[0m    %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; }

probe_host() { curl -sS --max-time 3 -f "$1/api/version" 2>&1; }
probe_container() {
  podman run --rm "$CURL_IMAGE" -sS --max-time 3 -f "$1/api/version" 2>&1 | tail -1
}

mode=$(wslinfo --networking-mode 2>/dev/null || echo unknown)
echo "Networking mode: $mode"
echo

# Candidate Windows addresses. In mirrored mode the default gateway is the LAN
# router, and Podman 4.9 maps host.containers.internal to a WSL-internal address
# on lo (10.255.255.254), so the WSL LAN IP (same as the Windows one) is the
# address that works from containers.
lan_ips=$(ip -4 -o addr show scope global | awk '$2 != "lo" {split($4, a, "/"); print a[1]}')
gw=$(ip route show default | awk '{print $3; exit}')
[[ "$mode" == "mirrored" ]] && gw=""

env_url=""
if [[ -f "$ROOT/.env" ]]; then
  env_url=$(sed -n 's/^OLLAMA_BASE_URL=//p' "$ROOT/.env" | tail -1)
fi

echo "1) From Ubuntu WSL"
if out=$(probe_host "http://localhost:$PORT"); then pass "http://localhost:$PORT  $out"; else fail "http://localhost:$PORT  $out"; fi
for ip in $lan_ips $gw; do
  if out=$(probe_host "http://$ip:$PORT"); then pass "http://$ip:$PORT  $out"; else fail "http://$ip:$PORT  $out"; fi
done

echo
echo "2) From a Podman container (what the app uses)"
candidates=()
[[ -n "$env_url" ]] && candidates+=("$env_url")
candidates+=("http://host.containers.internal:$PORT")
for ip in $lan_ips $gw; do candidates+=("http://$ip:$PORT"); done

recommended=""
declare -A seen=()
for url in "${candidates[@]}"; do
  [[ -n "${seen[$url]:-}" ]] && continue
  seen[$url]=1
  label="$url"
  [[ "$url" == "$env_url" ]] && label="$url (from .env)"
  if out=$(probe_container "$url"); then
    pass "$label  $out"
    [[ -z "$recommended" ]] && recommended="$url"
  else
    fail "$label  $out"
  fi
done

echo
if [[ -n "$recommended" ]]; then
  host_ip=$(sed -E 's#^https?://([^:/]+).*#\1#' <<<"$recommended")
  if [[ "$recommended" == "$env_url" ]]; then
    echo ".env is correct (OLLAMA_BASE_URL=$recommended)."
  else
    echo "Put this in .env:"
    [[ "$host_ip" != "host.containers.internal" ]] && echo "  OLLAMA_HOST_IP=$host_ip"
    echo "  OLLAMA_BASE_URL=$recommended"
  fi
  if [[ "$host_ip" =~ ^[0-9.]+$ ]]; then
    echo "  (This is a DHCP address. If it changes, rerun this script.)"
  fi
  echo
  echo "Models available:"
  podman run --rm "$CURL_IMAGE" -fsS --max-time 5 "$recommended/api/tags" | grep -o '"name":"[^"]*"' | cut -d'"' -f4 | sed 's/^/  /'
  exit 0
fi

cat <<EOF
Containers cannot reach Ollama. Check, in order:
  - Windows: Ollama is running and OLLAMA_HOST=0.0.0.0:11434 (scripts/windows/02_ollama-env.ps1)
  - Windows: .wslconfig has networkingMode=mirrored and hostAddressLoopback=true, then wsl --shutdown
  - Windows (admin): temporarily remove the LAN block rules: scripts/windows/03_ollama-firewall.ps1 -Remove
EOF
exit 1