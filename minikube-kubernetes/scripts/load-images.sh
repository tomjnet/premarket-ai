#!/usr/bin/env bash
# premarket-ai on Minikube: copies the images `make -C python build` made
# (rootless Podman storage) into the Minikube node, so nothing is rebuilt
# and no registry is needed. The manifests use the same names with
# imagePullPolicy: Never.
# Usage: scripts/load-images.sh [IMAGE...]  (default: every app image)
set -euo pipefail

prefix=${PREFIX:-localhost/premarket-ai}
minikube=${MINIKUBE:-minikube}
images=("$@")
if (( ${#images[@]} == 0 )); then
  images=(vendor-sim:dev ingest:dev ai-api:dev ai-api:worker
          mcp-server:dev scheduler:dev web:dev)
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

for image in "${images[@]}"; do
  ref="$prefix/$image"
  if ! podman image exists "$ref"; then
    echo "error: $ref not found; run make -C python build first" >&2
    exit 1
  fi
  echo "== $ref"
  podman save --format docker-archive -o "$tmp/image.tar" "$ref"
  # --overwrite: a rebuilt :dev tag replaces the old one in the node.
  $minikube image load --overwrite=true "$tmp/image.tar"
  rm -f "$tmp/image.tar"
done

$minikube image ls | grep "$prefix/" || true
