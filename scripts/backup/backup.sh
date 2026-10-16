#!/usr/bin/env sh
# Backup cifrado do PostgreSQL: pg_dump (formato custom) | gpg --symmetric AES256.
# Uso: backup.sh once | loop
set -eu
PGPASSWORD="$(cat /run/secrets/postgres_password)"
export PGPASSWORD
PASS=/run/secrets/backup_passphrase
DIR=/backups
INTERVAL_H="${BACKUP_INTERVAL_HOURS:-24}"
RETENTION_D="${BACKUP_RETENTION_DAYS:-14}"

run_once() {
  ts=$(date -u +%Y%m%dT%H%M%SZ)
  out="$DIR/tradewatch-$ts.dump.gpg"
  tmp="$out.partial"
  pg_dump -Fc --no-owner --no-privileges | gpg --batch --yes --quiet --symmetric --cipher-algo AES256 \
    --passphrase-file "$PASS" -o "$tmp"
  mv "$tmp" "$out"
  echo "{\"event\":\"backup_created\",\"file\":\"$(basename "$out")\",\"bytes\":$(wc -c < "$out")}"
  find "$DIR" -name 'tradewatch-*.dump.gpg' -mtime +"$RETENTION_D" -print -delete | sed 's/^/{"event":"backup_pruned","file":"/; s/$/"}/'
}

mkdir -p "$DIR"
case "${1:-once}" in
  once) run_once ;;
  loop)
    until pg_isready -q; do sleep 2; done
    while true; do
      run_once || echo '{"event":"backup_failed"}'
      sleep $((INTERVAL_H * 3600))
    done
    ;;
  *) echo "uso: backup.sh once|loop" >&2; exit 2 ;;
esac
