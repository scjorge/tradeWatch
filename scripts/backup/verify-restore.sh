#!/usr/bin/env sh
# Teste de restauração: restaura o backup em um banco temporário, valida e remove o banco.
# Uso: verify-restore.sh [/backups/arquivo.dump.gpg]   (padrão: o mais recente)
set -eu
PGPASSWORD="$(cat /run/secrets/postgres_password)"
export PGPASSWORD
# shellcheck disable=SC2012 # nomes gerados pelo próprio backup.sh, sem espaços
file="${1:-$(ls -1t /backups/tradewatch-*.dump.gpg | head -1)}"
check_db="tradewatch_restore_check_$$"
cleanup() { dropdb --if-exists "$check_db" >/dev/null 2>&1 || true; }
trap cleanup EXIT

createdb "$check_db"
gpg --batch --quiet --decrypt --passphrase-file /run/secrets/backup_passphrase "$file" \
  | pg_restore --no-owner --no-privileges -d "$check_db"

q() { psql -d "$check_db" -tAc "$1"; }
version=$(q "select version_num from alembic_version")
tables=$(q "select count(*) from information_schema.tables where table_schema='public'")
users=$(q "select count(*) from users")
execs=$(q "select count(*) from trade_executions")
dups=$(q "select count(*) from (select connection_id, idempotency_key from trade_executions group by 1,2 having count(*)>1) d")

[ -n "$version" ] || { echo "FALHA: alembic_version ausente"; exit 1; }
[ "$tables" -ge 20 ] || { echo "FALHA: apenas $tables tabelas"; exit 1; }
[ "$dups" = "0" ] || { echo "FALHA: execuções duplicadas"; exit 1; }
echo "OK: $(basename "$file") restaurado — migração $version, $tables tabelas, $users usuário(s), $execs execução(ões)."
