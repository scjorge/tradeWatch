# Funções para ler e gravar variáveis no .env (usado por generate-secrets.sh e rotate-credentials-key.sh).

ENV_FILE="${ENV_FILE:-.env}"

env_get() {
  grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2-
}

# Substitui a primeira linha "NOME=" ou acrescenta no fim do arquivo, preservando as permissões.
env_set() {
  tmp="$ENV_FILE.tmp.$$"
  if grep -qE "^$1=" "$ENV_FILE"; then
    K="$1" V="$2" awk '!d && index($0, ENVIRON["K"] "=") == 1 { print ENVIRON["K"] "=" ENVIRON["V"]; d = 1; next } { print }' \
      "$ENV_FILE" > "$tmp"
  else
    cat "$ENV_FILE" > "$tmp"
    [ -z "$(tail -c1 "$tmp")" ] || echo >> "$tmp"
    printf '%s=%s\n' "$1" "$2" >> "$tmp"
  fi
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
}
