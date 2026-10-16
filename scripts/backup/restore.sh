#!/usr/bin/env sh
# Restaura um backup cifrado. ATENÇÃO: substitui os dados do banco de destino.
# Uso: restore.sh /backups/tradewatch-XXXX.dump.gpg [banco_destino]
set -eu
file="$1"
target="${2:-$PGDATABASE}"
: "${PGPASSWORD:?defina PGPASSWORD}" "${BACKUP_PASSPHRASE:?defina BACKUP_PASSPHRASE}"
gpg --batch --quiet --decrypt --pinentry-mode loopback --passphrase-fd 3 "$file" 3<<EOF | pg_restore --clean --if-exists --no-owner --no-privileges -d "$target"
$BACKUP_PASSPHRASE
EOF
echo "Restaurado em $target a partir de $(basename "$file")."
