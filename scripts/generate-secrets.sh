#!/usr/bin/env sh
# Preenche os segredos no .env (só os que estiverem vazios; nunca sobrescreve um valor existente).
# Se existir a pasta antiga ./secrets (Docker secrets), os valores são importados de lá.
# Uso: ./scripts/generate-secrets.sh [arquivo .env]
set -eu
cd "$(dirname "$0")/.."
ENV_FILE="${1:-.env}"
. scripts/env-lib.sh

[ -f "$ENV_FILE" ] || { echo "Arquivo $ENV_FILE não encontrado. Crie antes: cp .env.example $ENV_FILE" >&2; exit 1; }

gen() { openssl rand -base64 "$1" | tr -d '\n'; }

legacy() {
  f="secrets/$1"
  [ -s "$f" ] || return 1
  if [ "$1" = credentials_keys ]; then
    grep -vE '^[[:space:]]*(#|$)' "$f" | tr -d ' \r' | paste -sd, -
  else
    tr -d '\r\n' < "$f"
  fi
}

ensure() {
  name="$1" file="$2" value="$3"
  if [ -n "$(env_get "$name")" ]; then
    echo "mantido:    $name"
  elif old=$(legacy "$file"); then
    env_set "$name" "$old"
    echo "importado:  $name (de secrets/$file)"
  else
    env_set "$name" "$value"
    echo "gerado:     $name"
  fi
}

ensure POSTGRES_PASSWORD postgres_password "$(gen 32 | tr '/+' '_-')"
ensure CREDENTIALS_KEYS credentials_keys "1:$(gen 32)"
ensure BACKUP_PASSPHRASE backup_passphrase "$(gen 48)"

# A senha do SMTP não é gerada: preencha SMTP_PASSWORD no .env se o seu servidor de e-mail exigir.
if [ -z "$(env_get SMTP_PASSWORD)" ] && old=$(legacy smtp_password); then
  env_set SMTP_PASSWORD "'$old'"
  echo "importado:  SMTP_PASSWORD (de secrets/smtp_password)"
elif ! grep -qE '^SMTP_PASSWORD=' "$ENV_FILE"; then
  env_set SMTP_PASSWORD ""
fi

chmod 600 "$ENV_FILE"
echo
echo "Segredos gravados em $ENV_FILE (permissão 600)."
echo "Guarde CREDENTIALS_KEYS e BACKUP_PASSPHRASE também em local seguro (gerenciador de senhas)."
[ ! -d secrets ] || echo "A pasta ./secrets não é mais usada; depois de conferir o .env, pode apagá-la."
