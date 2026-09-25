#!/usr/bin/env bash
# Checks that Windows Ollama is reachable from Ubuntu WSL and from Podman containers,
# and prints the OLLAMA_BASE_URL to put in .env.
# Usage: scripts/wsl/03_check-ollama.sh
set -uo pipefail

CURL_IMAGE="docker.io/curlimages/curl:latest"
PORT=11434
pass() { printf '  \033[32mOK\033[0m    %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; }

probe_host() { curl -fsS --max-time 3 "$1/api/version" 2>/dev/null; }

echo "Networking mode: $(wslinfo --networking-mode 2>/dev/null || echo unknown)"
echo

echo "1) From Ubuntu WSL"
if out=$(probe_host "http://localhost:$PORT"); then pass "http://localhost:$PORT  $out"; else fail "http://localhost:$PORT"; fi

gw=$(ip route show default | awk '{print $3; exit}')
if [[ -n "$gw" ]]; then
  if out=$(probe_host "http://$gw:$PORT"); then pass "http://$gw:$PORT (default gateway)  $out"; else fail "http://$gw:$PORT (default gateway)"; fi
fi

echo
echo "2) From a Podman container (what the app uses)"
recommended=""
url="http://host.containers.internal:$PORT"
if out=$(podman run --rm "$CURL_IMAGE" -fsS --max-time 3 "$url/api/version" 2>/dev/null); then
  pass "$url  $out"; recommended="$url"
else
  fail "$url"
fi

if [[ -z "$recommended" && -n "$gw" ]]; then
  url="http://$gw:$PORT"
  if out=$(podman run --rm "$CURL_IMAGE" -fsS --max-time 3 "$url/api/version" 2>/dev/null); then
    pass "$url  $out"; recommended="$url"
  else
    fail "$url"
  fi
fi

echo
if [[ -n "$recommended" ]]; then
  echo "Put this in .env:"
  echo "  OLLAMA_BASE_URL=$recommended"
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
