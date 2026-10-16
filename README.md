# TradeWatch

Plataforma web multiusuário para **acompanhar** operações em corretoras — começando pela Binance —
com saldos, histórico de execuções, apuração de lucros e prejuízos (FIFO ou custo médio),
evolução do patrimônio e notificações pelo Telegram.

> **Somente leitura.** O TradeWatch não envia ordens nem faz saques. Chaves de API com permissão
> de negociação, saque ou transferência são recusadas na validação.

- Backend: Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16
- Worker: mesmo código-base, fila no PostgreSQL
- Frontend: React 18 · TypeScript · Mantine 7 · TanStack Query
- Execução: Docker Compose (compatível com Traefik)

Arquitetura, contratos entre módulos, modelo de dados, decisões de segurança e metodologia de cálculo:
**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Instalação com Docker Compose

Requisitos: Docker 24+ com Compose v2.24+, `openssl`.

```bash
./scripts/generate-secrets.sh
```

```bash
cp .env.example .env
```

Para testar localmente em `http://localhost`, edite o `.env` e defina `APP_ENV=development`
(e `COOKIE_SECURE=false` se usar Safari).

Se acessar por outro endereço (IP da máquina, nome na rede), ajuste `APP_BASE_URL` para esse endereço;
ele é usado nos links de e-mail. Acessos pelo mesmo host e porta da requisição já são aceitos na
checagem de origem. Endereços adicionais vão em `ALLOWED_ORIGINS`. Sem HTTPS, fora de `localhost`, o navegador
descarta cookies `Secure`: use `COOKIE_SECURE=false` apenas nesse cenário de teste.

Depois:

```bash
docker compose up -d --build
```

| Serviço | Endereço |
|---|---|
| Aplicação | http://localhost:8080 |
| Documentação da API (OpenAPI) | http://localhost:8080/api/docs |
| E-mails de desenvolvimento (Mailpit) | http://localhost:8025 |

O serviço `migrate` aplica as migrações (`alembic upgrade head`) e semeia papéis, permissões,
módulos e corretoras antes de `api` e `worker` subirem.

### Primeiro acesso

1. Abra http://localhost:8080 → **Criar conta**.
2. Confirme o e-mail pelo link que chega no Mailpit (http://localhost:8025).
3. Entre e vá em **Integrações → Adicionar**. O formulário mostra o passo a passo para criar
   a chave na Binance com **apenas "Ativar leitura"**.

Para tornar um usuário administrador:

```bash
docker compose run --rm api python -m app.cli create-admin voce@exemplo.com
```

## Funcionalidades

| Área | O que faz |
|---|---|
| Visão geral | patrimônio, resultado realizado (líquido/bruto) e não realizado, rentabilidade, taxa de acerto, ganho/perda médios, melhor/pior operação, evolução do patrimônio, resultado por período, distribuição, atividade recente, estado das integrações; filtros globais por período, conta, corretora, ativo, mercado e tipo |
| Trades | posições calculadas (custo médio, custo total, cotação com fonte/horário, não realizado), conciliação com o saldo da corretora, registros de resultado realizado (completos/incompletos) |
| Operações | aba **Compra e venda**: cada compra casada com a venda que a encerrou (Status, Criptomoeda, Moeda, conta, data/quantidade/valor unitário de compra e venda, taxa, valores na moeda e em BRL, Lucro / Prejuízo, % e dias), com filtros por período (este mês, mês anterior, este ano…), resultado (lucro/prejuízo/incompletas), faixa de lucro em R$, %, dias, status, moeda, conta e ativo; indicadores (acerto, ganho/perda média, payoff, fator de lucro, melhor/pior, tempo médio, taxas, efeito câmbio); abas Por período, Calendário e Por ativo; execuções, ordens e depósitos/retiradas; exportação CSV |
| Carteiras e saldos | saldo por ativo/conta, valor estimado, % da carteira, histórico por snapshots, comparação entre datas |
| Relatórios | resultado e taxas por dia/semana/mês |
| Integrações | múltiplas conexões, validação antes de ativar, estados (pendente, ativa, sincronizando, com erro, credencial inválida, suspensa), sincronização manual, suspender/reativar, substituir credencial (sem nunca exibir a anterior), remover, histórico de sincronizações e erros, pares adicionais |
| Notificações | bot do Telegram com verificação de destino por código, mensagem de teste, ativar/desativar, escolha de eventos (compra/venda detectada, nova execução, sincronização concluída, falha de integração, credencial inválida, resumo diário, variação de patrimônio), histórico de envios e falhas |
| Configurações | perfil, fuso horário, moeda-base, método de custo, troca de senha, sessões ativas e revogação |
| Administração | saúde (API/banco/worker), métricas de sincronização, usuários e papéis, módulos, auditoria — sem acesso às credenciais |

### Operações: compra e venda

A aba **Operações → Compra e venda** mostra cada compra casada com a venda que a encerrou, montada a partir
das execuções sincronizadas da corretora. Os status são **Ordem Comprar** e **Ordem Vender** (ordens abertas na
corretora), **Ativo** (comprado e ainda não vendido) e **Concluído**.

| Campo | Cálculo |
|---|---|
| Total da compra | quantidade × valor unitário (na moeda de cotação) |
| Compra BRL | total × câmbio da compra; taxa paga em outro ativo (ex.: BNB) entra no custo |
| Quant. a vender | quantidade comprada − taxa (quando a taxa é cobrada no próprio ativo) |
| Total a venda | valor unitário de venda × quantidade − taxa da venda |
| Lucro / Prejuízo | Venda BRL − Compra BRL; % = lucro ÷ Compra BRL |

- Cada venda encerra as compras mais antigas do mesmo ativo (FIFO). Uma venda que encerra duas compras aparece em duas linhas.
- O câmbio para BRL é a cotação USDT/BRL do minuto da compra e da venda, então o efeito da variação do dólar aparece separado.
- Linhas "Ativo" mostram o resultado não realizado pela cotação atual, e "Ordem Vender" o resultado previsto pelo preço da ordem. Ambas são marcadas com `*` e não entram no lucro realizado.
- Venda sem compra correspondente (depósito externo, histórico indisponível na API) aparece como **incompleta** e fica fora das somas.
- **Taxa BRL**: taxas da compra e da venda daquela linha convertidas para BRL (taxas pagas em BNB pela cotação do momento).
- **Colunas**: o botão *Colunas* permite escolher o que aparece; além das padrão, há Câmbio Compra/Venda, Taxa Venda, Lucro na moeda e Efeito câmbio. A escolha fica salva no seu perfil (vale em qualquer navegador ou dispositivo), via `GET/PATCH /api/me/modules/{módulo}/settings`.
- **Filtros globais** (período, conta, ativo, mercado, tipo) também ficam salvos no perfil e são restaurados ao entrar de qualquer navegador.

### Quando a API não tem o histórico completo

O TradeWatch usa **somente dados da corretora**: não há importação de arquivos nem lançamentos manuais.
A Binance entrega execuções **por par** e não oferece todo o histórico (Convert, Earn, dust etc.):

- **Pares adicionais**: informe pares de ativos que você já zerou (ex.: `ETHUSDT`) para que sejam sincronizados.
- Vendas sem compra correspondente na API aparecem como **incompletas** e ficam fora das somas. O sistema não inventa valores.

## Operação

### Saúde

- `GET /api/health/live` — processo da API
- `GET /api/health/ready` — banco e último heartbeat do worker (HTTP 503 se o banco falhar)

Logs são JSON estruturados (`docker compose logs -f api worker`), sem segredos.

### Backups

O serviço `backup` gera `./backups/tradewatch-<data>.dump.gpg` a cada `BACKUP_INTERVAL_HOURS`
(padrão 24 h), cifrado com AES-256 usando `secrets/backup_passphrase`, mantendo `BACKUP_RETENTION_DAYS`.

Backup imediato:

```bash
docker compose run --rm backup backup.sh once
```

Teste de restauração (restaura em um banco temporário, valida e apaga):

```bash
docker compose run --rm backup verify-restore.sh
```

Restaurar de verdade (substitui os dados; pare `api` e `worker` antes):

```bash
docker compose stop api worker
```

```bash
docker compose run --rm backup restore.sh /backups/tradewatch-AAAAMMDDTHHMMSSZ.dump.gpg
```

```bash
docker compose start api worker
```

> Guarde `secrets/credentials_keys` e `secrets/backup_passphrase` **fora** do servidor (gerenciador de senhas).
> Sem a chave do cofre, as credenciais cifradas no banco restaurado não podem ser lidas.

### Rotação da chave do cofre

```bash
./scripts/rotate-credentials-key.sh
```

Adiciona uma nova versão em `secrets/credentials_keys`, reinicia `api`/`worker` e recifra todas as credenciais.

### Publicar as imagens no Docker Hub

Na sua máquina, com Docker (buildx) e `docker login` feito:

```bash
./scripts/build-push.sh -u SEU_USUARIO -t 1.0.0 --test
```

São publicadas três imagens, cada uma com a tag informada e `latest`:
`SEU_USUARIO/tradewatch-backend` (API, worker e migrações), `SEU_USUARIO/tradewatch-web` (frontend + nginx) e
`SEU_USUARIO/tradewatch-backup`. Por padrão são geradas para `linux/amd64` e `linux/arm64` (troque com
`-p linux/amd64`). Sem `-t`, a tag vem do git (`git describe`) ou da data. `--test` roda os testes antes de publicar,
e `--no-latest` não atualiza a tag `latest`.

### Implantar em produção (`docker-compose.prod.yml`)

No servidor você precisa só destes arquivos: `docker-compose.prod.yml`, `.env.production.example` e
`scripts/generate-secrets.sh`.

```bash
cp .env.production.example .env
```

Edite o `.env`: `IMAGE_NAMESPACE` (seu usuário do Docker Hub), `IMAGE_TAG`, `PUBLIC_HOST` (domínio),
`ACME_EMAIL` e o SMTP. Depois gere os segredos, grave a senha do SMTP em `secrets/smtp_password` e crie a
rede do proxy (apenas na primeira vez):

```bash
./scripts/generate-secrets.sh
```

```bash
docker network create traefik
```

Se o servidor **não** tem Traefik, suba com o Traefik incluído (portas 80/443, certificado Let's Encrypt automático):

```bash
docker compose -f docker-compose.prod.yml --profile traefik up -d
```

Se você **já tem** um Traefik na rede `traefik` (com entrypoint `websecure` e certresolver `le`, ajustáveis no `.env`):

```bash
docker compose -f docker-compose.prod.yml up -d
```

Criar o primeiro administrador:

```bash
docker compose -f docker-compose.prod.yml run --rm api python -m app.cli create-admin voce@seudominio.com.br
```

Atualizar para uma nova versão: altere `IMAGE_TAG` no `.env` e rode

```bash
docker compose -f docker-compose.prod.yml pull
```

```bash
docker compose -f docker-compose.prod.yml up -d
```

As migrações rodam sozinhas no serviço `migrate` antes de `api` e `worker`.

Diferenças em relação ao `docker-compose.yml` de desenvolvimento:
- usa as imagens do Docker Hub, sem build no servidor;
- só HTTPS (via Traefik), com HSTS e cookies `Secure`;
- sem Mailpit: SMTP real é obrigatório;
- containers do backend somente leitura e sem capabilities extras;
- logs com rotação (10 MB × 5 por serviço).

Os comandos de backup e restauração descritos acima funcionam igual; basta acrescentar `-f docker-compose.prod.yml`.

## Desenvolvimento

### Testes do backend (com Docker)

```bash
docker compose --profile test run --rm --build tests
```

Sem Docker, com um PostgreSQL descartável:

```bash
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

```bash
cd backend && TEST_DATABASE_URL=postgresql+psycopg://user:senha@localhost/tradewatch_test .venv/bin/pytest
```

A suíte (71 testes) cobre cadastro/autenticação, CSRF, bloqueio por tentativas, sessões, isolamento
entre usuários, cofre (AAD e rotação), redação de logs, idempotência e retomada da sincronização,
limites de requisição, motor de P&L (FIFO, custo médio, taxas, depósitos, transferências, conversões), operações compra → venda (FIFO, valores em BRL, filtros e resumo por período),
adaptador Binance com HTTP simulado, Telegram e migrações. **Nenhuma chave real é necessária.**

### Testes e build do frontend

```bash
cd frontend && npm ci && npm test && npm run build
```

### Rodar fora do Docker

API (porta 8000) e worker precisam de `DATABASE_URL` e `CREDENTIALS_KEYS` (`1:<base64 de 32 bytes>`):

```bash
cd backend && .venv/bin/alembic upgrade head && .venv/bin/python -m app.cli seed
```

```bash
cd backend && APP_ENV=development COOKIE_SECURE=false .venv/bin/uvicorn app.main:app --reload
```

```bash
cd backend && .venv/bin/python -m app.worker.main
```

```bash
cd frontend && npm run dev
```

O Vite (http://localhost:5173) faz proxy de `/api` para `localhost:8000`. Sem SMTP em
`APP_ENV=development`, o link de confirmação de e-mail aparece no log da API.

### Adicionar um módulo ou uma corretora

- **Módulo**: crie `app/modules/<nome>/` com rotas e defina um `ModuleSpec` (permissões, papéis, menu,
  tarefas periódicas) em `app/modules/registry.py`. Rode `python -m app.cli seed`.
- **Corretora**: implemente `ExchangeAdapter` em `app/integrations/<nome>/` e registre em
  `app/integrations/registry.py`. O módulo Trades não muda.

## Limitações desta versão

- MFA/TOTP preparado no modelo de dados, ainda sem fluxo de ativação.
- Binance: somente Spot com chaves HMAC; Convert/Earn/dust não sincronizados; sem streams em tempo real
  (sincronização a cada 15 min e manual).
- Rate limiting de autenticação em memória (uma réplica de API).
- Ainda sem testes de carga e revisão de segurança externa.

## Critérios de aceite (spec §11)

| # | Critério | Onde |
|---|---|---|
| 1 | Cadastro e uso da própria conta | `modules/auth`, `tests/test_auth.py` |
| 2 | Isolamento entre usuários | filtros por `user_id`, `tests/test_isolation_and_credentials.py` |
| 3 | Binance validada e sincronizada em somente leitura | `integrations/binance`, `tests/test_binance_adapter.py` |
| 4 | Sem execuções duplicadas | `UNIQUE(connection_id, idempotency_key)`, `tests/test_sync.py` |
| 5 | Metodologia e origem identificáveis | `docs/ARCHITECTURE.md §6`, fonte/horário da cotação nas telas |
| 6 | Filtros por data, ativo e corretora | `trades/filters.py`, `test_filters_and_csv_export` |
| 7 | Telegram só para destino validado | `notifications/router.py`, `tests/test_notifications.py` |
| 8 | Nenhuma credencial em frontend/logs/erros | `core/redaction.py`, testes de redação |
| 9 | Recuperação de falhas temporárias | checkpoints + backoff, `test_sync_resumes_after_failure_without_duplicates` |
| 10 | Novo módulo sem reescrever o núcleo | `ModuleSpec` + `REGISTRY` |
| 11 | Instalação por Docker Compose | `docker-compose.yml` |
| 12 | Backups restauráveis e validados | `scripts/backup/verify-restore.sh` |
