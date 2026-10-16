Este diretório guarda os segredos montados como Docker secrets. Nada aqui é versionado.

Gere tudo com `./scripts/generate-secrets.sh`. Arquivos:

- `postgres_password` — senha do PostgreSQL
- `credentials_keys` — chaves mestras AES-256 do cofre, uma por linha `versão:base64`
- `backup_passphrase` — senha usada para cifrar os backups (GPG/AES-256)
- `smtp_password` — senha do SMTP (pode ficar vazio)

Guarde `credentials_keys` e `backup_passphrase` em um gerenciador de senhas, **fora** do servidor de backup.
Sem `credentials_keys` as credenciais cifradas no banco não podem ser lidas.
