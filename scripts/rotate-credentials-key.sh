#!/usr/bin/env sh
# Adiciona uma nova versão de chave ao cofre e recifra todas as credenciais.
set -eu
cd "$(dirname "$0")/.."
last=$(cut -d: -f1 secrets/credentials_keys | sort -n | tail -1)
next=$((last + 1))
printf '\n%s:%s' "$next" "$(openssl rand -base64 32 | tr -d '\n')" >> secrets/credentials_keys
echo "Nova chave versão $next adicionada."
docker compose up -d --force-recreate api worker
docker compose run --rm -e CREDENTIALS_ACTIVE_KEY_VERSION="$next" api python -m app.cli rotate-keys
echo "Concluído. Mantenha as versões antigas no arquivo até confirmar que nada mais as usa."
