#!/usr/bin/env sh
# Restaura um backup cifrado. ATENÇÃO: substitui os dados do banco de destino.
# Uso: restore.sh /backups/tradewatch-XXXX.dump.gpg [banco_destino]
set -eu
file="$1"
target="${2:-$PGDATABASE}"
PGPASSWORD="$(cat /run/secrets/postgres_password)"
export PGPASSWORD
gpg --batch --quiet --decrypt --passphrase-file /run/secrets/backup_passphrase "$file" \
  | pg_restore --clean --if-exists --no-owner --no-privileges -d "$target"
echo "Restaurado em $target a partir de $(basename "$file")."
