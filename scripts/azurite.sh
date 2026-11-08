#!/usr/bin/env bash
# Start or stop a local Azurite blob emulator with rootless podman on a random free port.
# Usage: eval "$(scripts/azurite.sh start)"   then   scripts/azurite.sh stop
set -euo pipefail
NAME="fhir-azurite-local"
IMAGE="mcr.microsoft.com/azure-storage/azurite:3.35.0"
# Public, documented Azurite emulator account key. It is not a secret.
KEY="Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
case "${1:-}" in
  start)
    PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
    podman rm -f "$NAME" >/dev/null 2>&1 || true
    podman run -d --rm --name "$NAME" -p "127.0.0.1:${PORT}:10000" "$IMAGE" \
      azurite-blob --blobHost 0.0.0.0 --skipApiVersionCheck >/dev/null
    for _ in $(seq 1 60); do
      (exec 3<>"/dev/tcp/127.0.0.1/${PORT}") 2>/dev/null && break || sleep 0.5
    done
    echo "export AZURE_STORAGE_CONNECTION_STRING='DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=${KEY};BlobEndpoint=http://127.0.0.1:${PORT}/devstoreaccount1;'"
    ;;
  stop)
    podman rm -f "$NAME" >/dev/null 2>&1 || true
    ;;
  *) echo "usage: $0 start|stop" >&2; exit 2 ;;
esac
