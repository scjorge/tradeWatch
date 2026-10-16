#!/usr/bin/env sh
# Gera os segredos locais em ./secrets (não sobrescreve arquivos existentes).
set -eu
cd "$(dirname "$0")/.."
mkdir -p secrets
chmod 700 secrets

gen() { openssl rand -base64 "$1" | tr -d '\n'; }

write() {
  f="secrets/$1"
  if [ -s "$f" ] || { [ -e "$f" ] && [ "$1" = "smtp_password" ]; }; then
    echo "mantido:  $f"
  else
    printf '%s' "$2" > "$f"
    echo "criado:   $f"
  fi
  # 644 dentro de um diretório 700: legível pelo usuário do container, inacessível a outros usuários do host.
  chmod 644 "$f"
}

write postgres_password "$(gen 32 | tr '/+' '_-')"
write credentials_keys "1:$(gen 32)"
write backup_passphrase "$(gen 48)"
write smtp_password ""

echo
echo "Guarde secrets/credentials_keys e secrets/backup_passphrase em local seguro (gerenciador de senhas)."
