#!/usr/bin/env bash
# Installs /etc/wsl.conf and the premarket-ai sysctl settings inside Ubuntu-24.04.
# Usage (from your normal user):  sudo scripts/wsl/00_setup-wsl.sh
# Then from Windows PowerShell:    wsl --shutdown
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi
USER_NAME="${SUDO_USER:-}"
if [[ -z "$USER_NAME" || "$USER_NAME" == "root" ]]; then
  echo "Run it via sudo from your normal Linux user (it becomes the WSL default user)." >&2
  exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ts="$(date +%Y%m%d-%H%M%S)"

if [[ -f /etc/wsl.conf ]]; then
  cp /etc/wsl.conf "/etc/wsl.conf.bak-$ts"
  echo "Backed up /etc/wsl.conf to /etc/wsl.conf.bak-$ts"
fi
sed "s/<your-linux-user>/${USER_NAME}/" "$HERE/wsl.conf.example" | tr -d '\r' > /etc/wsl.conf
chmod 644 /etc/wsl.conf
echo "Installed /etc/wsl.conf (default user: $USER_NAME)"

tr -d '\r' < "$HERE/99-premarket.conf" > /etc/sysctl.d/99-premarket.conf
chmod 644 /etc/sysctl.d/99-premarket.conf
sysctl --system >/dev/null
echo "Installed /etc/sysctl.d/99-premarket.conf (vm.overcommit_memory=$(sysctl -n vm.overcommit_memory))"

cat <<EOF

Next:
  1. From Windows PowerShell:  wsl --shutdown   (wait ~8 seconds)
  2. Open Ubuntu again and check:
       systemctl is-system-running   # running (or degraded)
       echo \$PATH                    # no /mnt/c/... entries
EOF
