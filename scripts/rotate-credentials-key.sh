#!/usr/bin/env sh
# Adiciona uma nova versão de chave ao cofre (CREDENTIALS_KEYS no .env) e recifra todas as credenciais.
set -eu
cd "$(dirname "$0")/.."
. scripts/env-lib.sh
keys=$(env_get CREDENTIALS_KEYS)
[ -n "$keys" ] || { echo "CREDENTIALS_KEYS vazio em $ENV_FILE." >&2; exit 1; }
last=$(echo "$keys" | tr ',' '\n' | cut -d: -f1 | sort -n | tail -1)
next=$((last + 1))
env_set CREDENTIALS_KEYS "$keys,$next:$(openssl rand -base64 32 | tr -d '\n')"
echo "Nova chave versão $next adicionada."
docker compose up -d --force-recreate api worker
docker compose run --rm -e CREDENTIALS_ACTIVE_KEY_VERSION="$next" api python -m app.cli rotate-keys
echo "Concluído. Mantenha as versões antigas em CREDENTIALS_KEYS até confirmar que nada mais as usa."
