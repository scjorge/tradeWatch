#!/usr/bin/env bash
# Gera as imagens do TradeWatch e envia para o Docker Hub.
#
# Uso:
#   ./scripts/build-push.sh -u <usuario-dockerhub> [-t <tag>] [-p <plataformas>] [--test] [--no-latest]
#
# Exemplos:
#   ./scripts/build-push.sh -u jorge                      # tag = versão do git (ou data) + latest
#   ./scripts/build-push.sh -u jorge -t 1.0.0 --test      # roda os testes antes de publicar
#   DOCKERHUB_USER=jorge ./scripts/build-push.sh -p linux/amd64
#
# Imagens publicadas:
#   <usuario>/tradewatch-backend   (API, worker e migrações)
#   <usuario>/tradewatch-web       (frontend + nginx)
#   <usuario>/tradewatch-backup    (pg_dump cifrado)
#
# Pré-requisitos: Docker com buildx e "docker login" feito na conta do Docker Hub.
set -euo pipefail
cd "$(dirname "$0")/.."

USER_NS="${DOCKERHUB_USER:-}"
TAG="${TAG:-}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
RUN_TESTS=0
PUSH_LATEST=1

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    -u|--user) USER_NS="$2"; shift 2 ;;
    -t|--tag) TAG="$2"; shift 2 ;;
    -p|--platforms) PLATFORMS="$2"; shift 2 ;;
    --test) RUN_TESTS=1; shift ;;
    --no-latest) PUSH_LATEST=0; shift ;;
    -h|--help) usage 0 ;;
    *) echo "Opção desconhecida: $1" >&2; usage 1 ;;
  esac
done

[ -n "$USER_NS" ] || { echo "Informe o usuário do Docker Hub: -u <usuario> (ou DOCKERHUB_USER)." >&2; exit 1; }
command -v docker >/dev/null || { echo "Docker não encontrado." >&2; exit 1; }
docker buildx version >/dev/null 2>&1 || { echo "Docker buildx não disponível." >&2; exit 1; }

if [ -z "$TAG" ]; then
  if git rev-parse --short HEAD >/dev/null 2>&1; then
    TAG="$(git describe --tags --always --dirty 2>/dev/null || git rev-parse --short HEAD)"
  else
    TAG="$(date -u +%Y%m%d-%H%M%S)"
  fi
fi
# Tags do Docker aceitam [A-Za-z0-9_.-]
TAG="$(printf '%s' "$TAG" | tr -c 'A-Za-z0-9_.-' '-')"

if git status --porcelain >/dev/null 2>&1 && [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  echo "Aviso: há alterações não commitadas; a imagem incluirá o estado atual da pasta." >&2
fi

if [ "$RUN_TESTS" = 1 ]; then
  echo "==> Testes do backend"
  docker compose --profile test run --rm --build tests
  docker compose --profile test down -v >/dev/null 2>&1 || true
  echo "==> Testes e build do frontend"
  docker run --rm -v "$PWD/frontend:/app" -w /app node:22-alpine sh -c "npm ci --no-audit --no-fund && npm test && npm run build"
fi

BUILDER=tradewatch-builder
if ! docker buildx inspect "$BUILDER" >/dev/null 2>&1; then
  docker buildx create --name "$BUILDER" --driver docker-container >/dev/null
fi

REVISION="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
CREATED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

build() {
  local name="$1" context="$2"; shift 2
  local image="$USER_NS/$name"
  local tags=(-t "$image:$TAG")
  [ "$PUSH_LATEST" = 1 ] && tags+=(-t "$image:latest")
  echo "==> $image:$TAG ($PLATFORMS)"
  docker buildx build --builder "$BUILDER" --platform "$PLATFORMS" "${tags[@]}" \
    --label "org.opencontainers.image.title=$name" \
    --label "org.opencontainers.image.version=$TAG" \
    --label "org.opencontainers.image.revision=$REVISION" \
    --label "org.opencontainers.image.created=$CREATED" \
    --provenance=false \
    "$@" --push "$context"
}

build tradewatch-backend ./backend --target runtime
build tradewatch-web ./frontend
build tradewatch-backup ./scripts/backup

echo
echo "Publicado no Docker Hub:"
for n in backend web backup; do
  echo "  $USER_NS/tradewatch-$n:$TAG$([ "$PUSH_LATEST" = 1 ] && echo " (e :latest)")"
done
echo
echo "No servidor, defina no .env: IMAGE_NAMESPACE=$USER_NS e IMAGE_TAG=$TAG"
echo "e rode: docker compose -f docker-compose.prod.yml up -d"
