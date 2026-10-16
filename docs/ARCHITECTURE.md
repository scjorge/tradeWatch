# TradeWatch — Arquitetura, contratos e decisões

Este documento atende à seção 12 da especificação (`spec.md`): arquitetura, árvore de diretórios,
contratos entre módulos, modelo de dados, decisões de segurança, metodologia de cálculo e plano por fases.

## 1. Visão geral

```
                ┌────────────── navegador ──────────────┐
                │  React + TypeScript + Mantine (SPA)   │
                └───────────────┬───────────────────────┘
                                │ HTTPS (mesma origem, cookie HttpOnly + CSRF)
                     ┌──────────▼──────────┐
                     │  web (nginx)        │  serve o SPA, proxy /api → api, CSP
                     └──────────┬──────────┘
                                │
          ┌─────────────────────▼─────────────────────┐
          │ api (FastAPI)                             │
          │  núcleo: auth, usuários, módulos, auditoria│
          │  módulo trades · módulo notificações       │
          └───────┬───────────────────────────┬───────┘
                  │ SQL                        │ (validação de credenciais)
          ┌───────▼────────┐          ┌────────▼────────┐
          │ PostgreSQL 16  │◄─────────┤ worker          │──► Binance (somente leitura)
          │ dados + fila   │  SKIP    │ mesmo código    │──► Telegram Bot API
          └───────┬────────┘  LOCKED  └─────────────────┘
                  │ pg_dump | gpg AES256
          ┌───────▼────────┐
          │ backup         │ → ./backups/*.dump.gpg
          └────────────────┘
```

- **Monorepositório**, sem microsserviços: `backend/` (API + worker no mesmo código), `frontend/`.
- **Fila no PostgreSQL** (`sync_jobs` com `FOR UPDATE SKIP LOCKED`) e **outbox** de notificações
  (`notification_events`). Sem Redis enquanto não houver necessidade de escala.
- **Rede `internal`** do Compose sem acesso à internet para banco, migração e backup; apenas API,
  worker e web têm saída.

## 2. Árvore de diretórios

```
tradeWatch/
├── docker-compose.yml            # db, migrate, api, worker, web, mailpit, backup (+ perfil test)
├── docker-compose.traefik.yml    # exemplo de publicação HTTPS via Traefik
├── .env.example                  # configuração não sensível
├── secrets/                      # Docker secrets (não versionado)
├── scripts/
│   ├── generate-secrets.sh
│   ├── rotate-credentials-key.sh
│   └── backup/ (Dockerfile, backup.sh, restore.sh, verify-restore.sh)
├── docs/ARCHITECTURE.md
├── backend/
│   ├── Dockerfile  alembic.ini  requirements*.txt
│   ├── alembic/versions/0001_initial_schema.py
│   ├── app/
│   │   ├── main.py               # cria a app, registra módulos, health
│   │   ├── config.py  db.py  cli.py
│   │   ├── core/                 # núcleo da plataforma
│   │   │   ├── security.py       # Argon2id, tokens opacos, força de senha
│   │   │   ├── crypto.py         # cofre AES-256-GCM com chaves versionadas
│   │   │   ├── credentials.py    # único ponto que decifra segredos
│   │   │   ├── deps.py           # sessão, CSRF, permissões, módulo habilitado
│   │   │   ├── modules.py        # contrato ModuleSpec
│   │   │   ├── audit.py  errors.py  logging.py  redaction.py  ratelimit.py  mailer.py
│   │   ├── models/               # SQLAlchemy (core, trades, notifications)
│   │   ├── integrations/         # contrato de corretoras + adaptadores
│   │   │   ├── base.py           # ExchangeAdapter, PriceSource, DTOs, erros
│   │   │   ├── registry.py
│   │   │   └── binance/ (client.py, adapter.py)
│   │   ├── modules/
│   │   │   ├── registry.py       # lista de módulos ativos no código
│   │   │   ├── auth/  users/  admin/
│   │   │   ├── trades/           # sync, pnl/engine, cycles (compra → venda), pricing, analytics, rotas, tarefas
│   │   │   └── notifications/    # contrato de canal, Telegram, outbox, rotas
│   │   └── worker/main.py
│   └── tests/                    # pytest (corretora e Telegram simulados)
└── frontend/
    ├── Dockerfile  nginx.conf  vite.config.ts
    └── src/ (api/, auth/, components/, layout/, pages/, test/)
```

## 3. Contratos entre módulos

### 3.1 Módulos da plataforma (`app/core/modules.py`)

```python
@dataclass
class ModuleSpec:
    key: str; name: str; description: str; version: str = "1"
    core: bool = False                        # núcleo não pode ser desativado
    routers: list[APIRouter]                  # rotas próprias
    permissions: dict[str, str]               # permissões que o módulo define
    role_permissions: dict[str, list[str]]    # papel → permissões padrão
    nav: list[NavItem]                        # itens do menu (filtrados por permissão)
    periodic_tasks: list[PeriodicTask]        # executadas pelo worker
```

O núcleo itera `REGISTRY` (`app/modules/registry.py`): inclui as rotas (com a dependência
`require_module(key)` para módulos não essenciais), semeia permissões/papéis/módulos
(`python -m app.cli seed`), monta o menu (`GET /api/me/modules`) e agenda as tarefas no worker.
**Adicionar um módulo = criar o pacote e acrescentá-lo ao `REGISTRY`.** Nada no núcleo muda.

### 3.2 Corretoras (`app/integrations/base.py`)

```python
class ExchangeAdapter(ABC):
    info: ClassVar[ProviderInfo]          # nome, campos de credencial, instruções, capacidades/limites
    def validate_credentials(self) -> ValidationResult
    def fetch_balances(self) -> list[BalanceDTO]
    def discover_symbols(self, assets, extra_symbols) -> list[SymbolInfo]
    def fetch_executions(self, symbol, cursor: dict) -> Page[ExecutionDTO]
    def fetch_orders(self, symbol, cursor: dict) -> Page[OrderDTO]
    def fetch_movements(self, kind, cursor: dict) -> Page[MovementDTO]   # depósitos/retiradas

class PriceSource(ABC):
    def current_prices(self) -> dict[(base, quote), Decimal]
    def historical_price(self, base, quote, at) -> Decimal | None
```

Erros padronizados: `InvalidCredentials`, `InsufficientPermissions`, `AdapterError` (definitivo),
`TemporaryError` e `RateLimited(retry_after)` (repetíveis). O módulo Trades (`sync.py`, `pnl/`,
`analytics.py`) **só conhece estes tipos** — nunca a API da Binance.

### 3.3 Notificações (`app/modules/notifications/base.py`)

```python
class NotificationChannelAdapter(ABC):
    kind: str
    def check(self) -> ChannelIdentity        # valida credencial do canal
    def send(self, destination: dict, text: str) -> None
```

Produtores chamam apenas `notifications.service.emit(db, user_id, event_type, message, payload, dedupe_key=)`.
O worker entrega (`deliver_pending`) com retentativas e backoff. Novo canal = novo adaptador.

## 4. Modelo de dados

Todas as chaves primárias são UUID. Datas em `timestamptz` (UTC); a conversão para o fuso do
usuário acontece na apresentação. Valores financeiros em `NUMERIC(38,18)` — nunca ponto flutuante.

| Entidade | Pontos principais |
|---|---|
| `users` | e-mail único, `password_hash` (Argon2id), bloqueio (`failed_login_count`, `locked_until`), preferências (`timezone`, `base_currency`, `cost_method`), campos de MFA preparados |
| `user_tokens` | verificação de e-mail / redefinição de senha; só o **hash** do token; uso único com expiração |
| `sessions` | hash do token de sessão e do token CSRF, expiração absoluta e por inatividade, revogação |
| `roles`, `permissions`, `role_permissions`, `user_roles` | RBAC |
| `modules`, `user_module_settings` | módulos habilitados globalmente e por usuário |
| `encrypted_credentials` | genérico (`owner_type`, `owner_id`), `key_version`, `nonce`, `ciphertext`, `hint` não sensível |
| `exchange_providers`, `exchange_connections` | conexão por usuário (`UNIQUE(user_id, name)`), estado, falhas consecutivas, configurações |
| `sync_jobs` | fila: estado, tentativas, `run_after` (backoff), heartbeat, erro sanitizado, estatísticas |
| `sync_checkpoints` | cursor por fluxo (`UNIQUE(connection_id, stream)`), ex.: `trades:BTCUSDT`, `movements:deposit` |
| `exchange_orders` | `UNIQUE(connection_id, external_id)`; estado atualizado por upsert |
| `trade_executions` | **idempotência** `UNIQUE(connection_id, idempotency_key)`; vínculo opcional à ordem; `fee_value` na moeda-base |
| `asset_movements` | depósitos/retiradas, `UNIQUE(connection_id, kind, external_id)` |
| `balances` | último saldo informado pela corretora |
| `balance_snapshots` | snapshot por sincronização com preço, fonte e horário da cotação |
| `asset_prices` | cotações (`UNIQUE(base, quote, source, price_at)`) |
| `positions`, `realized_pnl_records` | resultado da apuração (recalculado de forma determinística) |
| `notification_channels`, `notification_preferences`, `notification_events` | canais, preferências por evento, outbox/histórico com `dedupe_key` único |
| `trade_cycles` | operações compra → venda (lote comprado × venda que o encerrou, FIFO por ativo), valores em BRL pela cotação histórica; recalculadas a cada apuração (`modules/trades/cycles.py`) |
| `audit_logs` | ações de segurança e configuração, detalhes redigidos |
| `worker_heartbeats` | saúde do worker |

**Isolamento:** toda entidade de usuário tem `user_id` (FK com `ON DELETE CASCADE`). As rotas
sempre filtram por `user_id` do usuário autenticado e respondem 404 para recursos alheios.

**Chave de idempotência das execuções:**
- `ext:<id>` quando a corretora fornece identificador confiável (Binance: `id` do trade, único por par/conta).
- Estratégia alternativa (corretora sem identificador confiável): `hash:` + SHA-256 de
  `símbolo|lado|data ISO|quantidade|preço|taxa|ativo da taxa|id da ordem`.
- Apenas dados da corretora são aceitos: não há importação de arquivos nem lançamentos manuais.

## 5. Segurança — decisões

| Tema | Decisão |
|---|---|
| Senhas | Argon2id (t=3, m=64 MiB, p=2), rehash automático, política mínima de força, comparação em tempo constante e hash fictício para usuários inexistentes |
| Sessões | token opaco aleatório (256 bits) em cookie `HttpOnly`, `SameSite=Lax`, `Secure` em produção; servidor guarda só SHA-256; expiração absoluta (72 h) e por inatividade (12 h); revogação individual, "encerrar as outras", e revogação total ao redefinir senha |
| CSRF | double-submit: cookie `tw_csrf` (`SameSite=Strict`) ecoado em `X-CSRF-Token` e comparado ao hash da sessão; middleware rejeita `Content-Type` de formulário e `Origin` diferente em produção |
| Força bruta | rate limit por IP e por e-mail nas rotas de autenticação; bloqueio da conta após 5 falhas por 15 min (no banco, vale para várias réplicas) |
| Enumeração | cadastro, reenvio e recuperação respondem igual para e-mails existentes ou não |
| Credenciais | AES-256-GCM (`cryptography`), nonce aleatório de 96 bits, **AAD = tipo + id do dono + id do usuário** (um ciphertext copiado para outro registro não decifra), chave mestra fora do banco (Docker secret), versionamento e rotação (`app.cli rotate-keys`) |
| Acesso aos segredos | apenas `core/credentials.py` decifra; chamado somente na validação, no worker de sincronização e na entrega de notificações. Nenhuma rota retorna segredo; admin não tem rota para isso |
| Corretora | só chaves **somente leitura**: a validação consulta `apiRestrictions` e recusa chaves com saque, negociação, transferência, margem ou futuros; recomenda restrição por IP |
| Telegram | token cifrado; destino só é aceito quando o usuário envia um código de verificação (comparado por hash) no próprio chat/grupo |
| Logs | JSON estruturado com redação automática (tokens de bot, `signature=`, `apikey`, cabeçalhos, strings de 64 caracteres) e chaves sensíveis; `httpx` silenciado (a URL do Telegram contém o token) |
| Erros | respostas sem stack trace; código de incidente para correlação; mensagens de integrações sanitizadas antes de ir ao banco |
| Frontend | CSP restritiva no nginx, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`; tokens de e-mail no fragmento `#t=` (não chegam a logs de servidor) |
| Containers | usuário não root, `read_only`, `no-new-privileges`, segredos via `/run/secrets`, rede interna sem internet |
| Backups | `pg_dump` cifrado com GPG AES-256; script de teste de restauração; as chaves do cofre ficam fora do backup do banco |

## 6. Metodologia de apuração (P&L)

Implementada como função pura em `app/modules/trades/pnl/engine.py` e coberta por testes.

- Tudo é apurado na **moeda-base** do usuário (padrão USDT). Cotações históricas: kline de 1 minuto
  da Binance no minuto da operação (ponte via USDT quando necessário), com fonte e horário gravados.
- **Compra** BASE/QUOTE: entrega QUOTE (se QUOTE ≠ moeda-base, gera registro de *conversão* com ganho/perda
  do QUOTE) e adquire BASE com custo = valor entregue + taxa.
- **Venda**: entrega BASE (registro de *venda*: receita líquida − custo) e adquire QUOTE pelo valor recebido.
- **Taxas**: em BASE reduzem a quantidade recebida; em QUOTE somam ao custo/subtraem da receita; em
  terceiro ativo (BNB) consomem lotes desse ativo (registro do tipo *taxa*).
- **Depósitos externos** de cripto entram com **custo desconhecido**. Vendas desses lotes geram registros
  **incompletos** (sem valor inventado). Depósitos/retiradas nunca são lucro/prejuízo.
- **Transferências entre contas próprias** (mesmo `tx_id` em retirada e depósito do usuário) preservam o custo.
- **Métodos**: FIFO ou custo médio ponderado (preferência do usuário; troca recalcula tudo).
- **Resultado não realizado** = quantidade × cotação atual − custo, apenas quando o custo é conhecido.
- **Rentabilidade realizada** = resultado líquido ÷ custo das posições encerradas.
- **Bruto** = líquido + taxas pagas no período. Patrimônio ≠ lucro: a variação de patrimônio inclui aportes.
- Saldo **informado pela corretora** (`balances`), **calculado localmente** (`positions`) e **valor estimado**
  (cotação) são exibidos separadamente, com a diferença de conciliação.

## 7. Sincronização

- Fluxos por conexão: saldos → depósitos/retiradas (janelas de 89 dias) → por par: ordens e execuções.
- Paginação por cursor (`fromId`/`orderId`), checkpoint gravado na mesma transação de cada página →
  **retomável**; upserts com `ON CONFLICT` → **idempotente**.
- Ordens não finalizadas são revisitadas (o cursor volta ao menor `orderId` aberto) para atualizar o estado.
- Limites: lê `X-MBX-USED-WEIGHT-1M`/`X-SAPI-USED-UID-WEIGHT-1M` e pausa em 80% do teto; 429/418 viram
  `RateLimited` com `Retry-After`; histórico de saques é espaçado (limite por UID).
- Falhas temporárias: até 2 retentativas imediatas com backoff no cliente; depois o job volta à fila com
  backoff exponencial (30 s → 1 h, respeitando `Retry-After`) até `JOB_MAX_ATTEMPTS`.
  Credencial inválida interrompe sem retentativa e marca a conexão.
- Jobs presos (worker morto) são reenfileirados após `JOB_STALE_MINUTES` sem heartbeat.
- Falha de uma corretora afeta apenas a conexão: API e demais conexões seguem funcionando.
- Streams/WebSocket **não** foram implementados nesta versão (sincronização periódica a cada 15 min + manual).

## 8. Plano por fases e estado

| Fase | Itens | Estado |
|---|---|---|
| 1 — Fundação | estrutura, login/usuários, banco, segurança básica, layout, módulos | ✅ |
| 2 — Integração | conexões, cofre, adaptador Binance, sync incremental, saldos e execuções | ✅ |
| 3 — Análise | histórico, posições, P&L realizado/não realizado, filtros, gráficos, snapshots | ✅ |
| 4 — Notificações | Telegram, eventos, resumo diário, histórico | ✅ |
| 5 — Produção | auditoria ✅, health/métricas ✅, backups + teste de restauração ✅, documentação ✅; revisão de segurança externa e testes de carga ⏳ |

Pendências conhecidas (próximos passos):
- MFA/TOTP: colunas e flag de sessão prontos; fluxo de ativação não exposto.
- Binance: Convert, Earn, dust e margem/futuros não sincronizados (vendas desses saldos ficam incompletas). Chaves Ed25519/RSA não suportadas (somente HMAC).
- Rate limit em memória (uma réplica da API). Para várias réplicas, trocar por Redis.
- Testes de carga e pentest externo.
