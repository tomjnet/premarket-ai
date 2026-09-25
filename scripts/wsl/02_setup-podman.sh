#!/usr/bin/env bash
# Installs rootless Podman + docker-compose v2 (as the `podman compose` provider)
# inside Ubuntu-24.04 on WSL2, and enables the user services premarket-ai needs.
# Usage (normal user, NOT sudo; it calls sudo when needed):
#   scripts/wsl/02_setup-podman.sh
set -euo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Run as your normal user (it uses sudo when needed)." >&2
  exit 1
fi
if [[ "$(ps -p 1 -o comm=)" != "systemd" ]]; then
  echo "systemd is not running. Run 'sudo scripts/wsl/00_setup-wsl.sh', then 'wsl --shutdown' from Windows." >&2
  exit 1
fi

echo "==> Installing packages"
sudo apt-get update
sudo apt-get install -y podman uidmap slirp4netns passt fuse-overlayfs dbus-user-session curl jq git

echo "==> Checking subordinate UID/GID ranges for rootless Podman"
if ! grep -q "^${USER}:" /etc/subuid || ! grep -q "^${USER}:" /etc/subgid; then
  sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 "$USER"
  podman system migrate
fi

echo "==> Installing docker-compose v2 (latest release, checksum verified)"
base="https://github.com/docker/compose/releases/latest/download"
asset="docker-compose-linux-$(uname -m)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fsSL -o "$tmp/$asset" "$base/$asset"
curl -fsSL -o "$tmp/$asset.sha256" "$base/$asset.sha256"
(cd "$tmp" && echo "$(cut -d' ' -f1 "$asset.sha256")  $asset" | sha256sum -c -)
sudo install -m 755 "$tmp/$asset" /usr/local/bin/docker-compose

echo "==> Configuring podman compose to use docker-compose v2"
mkdir -p "$HOME/.config/containers"
conf="$HOME/.config/containers/containers.conf"
if ! grep -q "compose_providers" "$conf" 2>/dev/null; then
  cat >> "$conf" <<'EOF'
[engine]
compose_providers = ["/usr/local/bin/docker-compose"]
compose_warning_logs = false
EOF
fi

echo "==> Enabling user services"
systemctl --user enable --now podman.socket
systemctl --user enable podman-restart.service
sudo loginctl enable-linger "$USER"

echo "==> Environment for Testcontainers / docker-compose (appended to ~/.bashrc once)"
if ! grep -q "premarket-ai podman env" "$HOME/.bashrc"; then
  cat >> "$HOME/.bashrc" <<'EOF'

# premarket-ai podman env
export DOCKER_HOST="unix://${XDG_RUNTIME_DIR}/podman/podman.sock"
export TESTCONTAINERS_RYUK_DISABLED=true
EOF
fi

echo "==> Verifying"
podman --version
podman compose version
podman run --rm quay.io/podman/hello

cat <<'EOF'

Podman is ready. Open a new shell (or `source ~/.bashrc`), then run:
  scripts/wsl/03_check-ollama.sh
EOF
