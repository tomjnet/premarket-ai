#!/usr/bin/env bash
# premarket-ai on Minikube: turns .env into Kubernetes config, like compose
# reads .env. Creates (or updates) in the namespace:
#   configmap premarket-settings  settings.env defaults, overridden by .env
#   secret    premarket-env       every other .env key (passwords, tokens)
#   configmap edge-templates      podman/config/edge/templates/
#                                 edge.conf.template with the upstream names
#                                 fully qualified (nginx's resolver doesn't
#                                 use the DNS search domains)
# Usage: scripts/config.sh [ENV_FILE] (default: <repo>/.env)
set -euo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
root=$(cd "$here/.." && pwd)
env_file=${1:-$root/.env}
ns=${NS:-premarket}
kubectl=${KUBECTL:-kubectl}

if [[ ! -f "$env_file" ]]; then
  echo "error: $env_file not found (cp .env.example .env && make -C python env)" >&2
  exit 1
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# .env as KEY=VALUE, one line per key (the last one wins, as in compose),
# no comments, no surrounding quotes.
awk '
  /^[[:space:]]*(#|$)/ { next }
  {
    sub(/^[[:space:]]*export[[:space:]]+/, "")
    i = index($0, "=")
    if (i == 0) next
    k = substr($0, 1, i - 1); v = substr($0, i + 1)
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", k)
    if (v ~ /^".*"$/ || v ~ /^\x27.*\x27$/) v = substr(v, 2, length(v) - 2)
    if (!(k in val)) order[++n] = k
    val[k] = v
  }
  END { for (j = 1; j <= n; j++) print order[j] "=" val[order[j]] }
' "$env_file" > "$tmp/env"

# Settings: the defaults of settings.env, replaced by non-empty .env values.
awk -F= '
  FNR == NR {
    if ($0 ~ /^[[:space:]]*(#|$)/) next
    k = $1; def[k] = substr($0, length(k) + 2); order[++n] = k; next
  }
  {
    k = $1; v = substr($0, length(k) + 2)
    if ((k in def) && (v != "" || k == "BRIEF_MODEL")) def[k] = v
  }
  END { for (j = 1; j <= n; j++) print order[j] "=" def[order[j]] }
' "$here/settings.env" "$tmp/env" > "$tmp/settings"

# Secrets: every .env key that is not a setting.
awk -F= '
  FNR == NR { if ($0 !~ /^[[:space:]]*(#|$)/) setting[$1] = 1; next }
  !($1 in setting)
' "$here/settings.env" "$tmp/env" > "$tmp/secrets"

# compose's ${VAR:?...}: stop early with the same hint.
missing=()
for key in POSTGRES_PASSWORD REDIS_PASSWORD AI_DB_PASSWORD JWT_SECRET \
    LLM_GATEWAY_KEY WORKER_DB_PASSWORD MCP_DB_PASSWORD MCP_SERVICE_TOKEN \
    SEARXNG_SECRET ALERT_WEBHOOK_TOKEN DEMO_USER_PASSWORD; do
  grep -q "^$key=." "$tmp/secrets" || missing+=("$key")
done
grep -q '^OLLAMA_BASE_URL=.' "$tmp/settings" || missing+=(OLLAMA_BASE_URL)
if (( ${#missing[@]} )); then
  echo "error: empty in $env_file: ${missing[*]}" >&2
  echo "       run make -C python env (OLLAMA_BASE_URL: scripts/wsl/03_check-ollama.sh)" >&2
  exit 1
fi
# host.containers.internal is Podman's name for the host: kube-dns doesn't
# know it, so the gateway could never reach Ollama.
if grep -q '^OLLAMA_BASE_URL=.*host\.containers\.internal' "$tmp/settings"; then
  echo "error: OLLAMA_BASE_URL uses host.containers.internal, which pods can't resolve" >&2
  echo "       set the GPU host's LAN address that scripts/wsl/03_check-ollama.sh prints" >&2
  exit 1
fi

# The edge's site config, from the one compose uses.
sed -E "s/^([[:space:]]*server[[:space:]]+)(web-1|web-2|ai-api):/\1\2.$ns.svc.cluster.local:/" \
  "$root/podman/config/edge/templates/edge.conf.template" > "$tmp/edge.conf.template"
if [[ $(grep -c "\.$ns\.svc\.cluster\.local:" "$tmp/edge.conf.template") -ne 3 ]]; then
  echo "error: expected 3 upstream servers in edge.conf.template" >&2
  exit 1
fi

apply() { $kubectl apply -f - >/dev/null; }
$kubectl create namespace "$ns" --dry-run=client -o yaml | apply
$kubectl -n "$ns" create configmap premarket-settings \
  --from-env-file="$tmp/settings" --dry-run=client -o yaml | apply
$kubectl -n "$ns" create secret generic premarket-env \
  --from-env-file="$tmp/secrets" --dry-run=client -o yaml | apply
$kubectl -n "$ns" create configmap edge-templates \
  --from-file=edge.conf.template="$tmp/edge.conf.template" \
  --dry-run=client -o yaml | apply

echo "namespace $ns: configmap premarket-settings ($(wc -l < "$tmp/settings") keys)," \
  "secret premarket-env ($(wc -l < "$tmp/secrets") keys), configmap edge-templates"
