# TradePulse — Especificação funcional e técnica

## 1. Objetivo

Desenvolver uma plataforma web multiusuário para acompanhamento de operações financeiras, com integração inicial à Binance, monitoramento de compras e vendas, cálculo de resultados, visualização de saldos e notificações pelo Telegram.

O sistema deve ter arquitetura modular, segurança como requisito central, interface intuitiva e capacidade de receber novos módulos futuramente.

O sistema será inicialmente de consulta e análise. Não deve executar ordens de compra ou venda nem permitir saques.

## 2. Requisitos funcionais

### 2.1. Autenticação e usuários

Implementar:

- Cadastro e login de usuários.
- Recuperação de senha por mecanismo seguro.
- Verificação de e-mail.
- Encerramento de sessões.
- Alteração de senha.
- Revogação de sessões e credenciais.
- Preparação para autenticação multifator (MFA).
- Isolamento completo dos dados entre usuários.
- Controle de acesso baseado em papéis e permissões.
- Registro de eventos relevantes de segurança.

Papéis iniciais:
- Usuário: acessa e administra somente os próprios dados.
- Administrador: administra a plataforma, os módulos e as configurações globais, sem acesso automático às chaves privadas dos usuários.

Não permitir que um usuário consulte, altere ou exclua dados pertencentes a outro usuário.

### 2.2. Dashboard principal

Criar um dashboard simples, responsivo e personalizável com:

- Patrimônio total acompanhado.
- Saldo por corretora e moeda.
- Lucro e prejuízo realizado.
- Resultado não realizado, quando calculável.
- Resultado líquido após taxas.
- Rentabilidade percentual.
- Quantidade de operações.
- Taxa de operações lucrativas.
- Ganho médio e perda média.
- Melhor e pior operação.
- Evolução do patrimônio.
- Gráfico de resultados por período.
- Distribuição dos ativos.
- Atividade recente.
- Estado das integrações.
- Última sincronização realizada.

Disponibilizar filtros globais por período, corretora, conta, ativo, mercado e tipo de operação.

Não confundir saldo atual com lucro, nem volume negociado com rentabilidade.

### 2.3. Cadastro de corretoras

Criar uma seção denominada "Integrações".

Permitir ao usuário:

- Cadastrar múltiplas conexões.
- Informar um nome amigável para cada conexão.
- Selecionar a corretora.
- No formulario de cadastro das chaves de API, deve ter instruções de como criar a chava na plataforma selecionada
- Informar as credenciais exigidas pela integração.
- Validar a conexão antes de ativá-la.
- Consultar o estado da conexão.
- Verificar a data da última sincronização.
- Atualizar ou substituir credenciais.
- Suspender e reativar uma integração.
- Remover uma conexão.
- Consultar o histórico de erros e sincronizações.

Estados possíveis:
- Pendente de validação.
- Ativa.
- Sincronizando.
- Com erro.
- Credencial inválida.
- Suspensa.

Deve poder ter a opção do usuário sincronizar manualmente.

Nunca apresentar chaves secretas em texto puro depois de cadastradas. Para atualizar uma credencial, solicitar o novo valor, sem recuperar ou exibir o anterior.

### 2.4. Integração com Binance

Implementar a Binance como primeira integração, por meio de um adaptador isolado do restante da aplicação.

Usar a API oficial e respeitar os limites de requisições.

Permitir sincronizar, conforme os endpoints e permissões disponíveis:

- Saldos de ativos.
- Ordens e seus estados.
- Operações executadas (trades).
- Quantidades compradas e vendidas.
- Preços de execução.
- Taxas e moedas utilizadas no pagamento das taxas.
- Depósitos e retiradas, quando autorizados e necessários para conciliação.
- Histórico disponível na API.
- Dados necessários para calcular posições e resultados.

Utilizar apenas permissões de leitura. Não solicitar permissões para saque ou negociação.

Priorizar consultas incrementais e sincronização periódica. Se houver suporte adequado, utilizar eventos ou streams para reduzir a latência, mantendo reconciliações periódicas via API.

A sincronização deve:
- Ser retomável após falhas.
- Respeitar limites de chamadas.
- Utilizar paginação e cursores.
- Evitar registros duplicados.
- Registrar o último ponto sincronizado.
- Permitir sincronização manual.
- Mostrar quando os dados foram atualizados pela última vez.

Não presumir que toda a movimentação histórica estará disponível indefinidamente na API. Implementar importação de arquivos ou outra estratégia de recuperação quando necessário.

### 2.5. Histórico de operações

Criar uma tabela pesquisável e paginada com:

- Data e hora.
- Corretora.
- Conta.
- Mercado.
- Par negociado.
- Lado: compra ou venda.
- Quantidade.
- Preço unitário.
- Valor bruto.
- Taxa.
- Moeda da taxa.
- Valor líquido, quando aplicável.
- Identificador externo da operação.
- Estado da sincronização.

Disponibilizar:
- Filtro por período.
- Filtro por corretora.
- Filtro por ativo ou par.
- Filtro por compra e venda.
- Filtro por faixa de valores.
- Ordenação por coluna.
- Pesquisa textual.
- Paginação.
- Exportação CSV.

Manter a distinção entre ordens e execuções. Uma ordem pode gerar várias execuções e não deve ser contada automaticamente como uma única operação concluída.

### 2.6. Cálculo de lucros e perdas

Implementar um mecanismo consistente de apuração de resultados.

Diferenciar claramente:

- Lucro ou prejuízo realizado.
- Lucro ou prejuízo não realizado.
- Taxas pagas.
- Depósitos e retiradas.
- Transferências entre contas próprias.
- Conversões entre ativos.
- Variação cambial.
- Resultado bruto e líquido.

Permitir selecionar um método de apuração de custo, como FIFO, conforme a metodologia definida pelo projeto.

O cálculo deve considerar taxas, quantidades, ativos recebidos ou entregues e histórico disponível. Não classificar depósitos como lucro nem retiradas como prejuízo.

Para calcular valores consolidados em uma moeda-base, registrar a fonte e o horário da cotação usada.

Quando houver dados insuficientes para calcular um resultado confiável, mostrar "incompleto" ou "não calculado", em vez de inventar valores.

### 2.7. Saldos e patrimônio

Criar uma tela de patrimônio com:

- Saldo por ativo.
- Saldo por corretora.
- Saldo por conta.
- Valor estimado em moeda-base.
- Distribuição percentual da carteira.
- Evolução histórica.
- Comparação entre períodos.

Diferenciar saldo informado pela corretora, saldo calculado localmente e valor estimado por cotação.

Guardar snapshots periódicos para possibilitar gráficos históricos sem depender da disponibilidade integral de dados antigos na corretora.

### 2.8. Telegram

Criar uma seção de configuração de notificações.

Permitir configurar um bot do Telegram e um destino de notificações, como chat privado ou grupo autorizado.

Implementar:
- Registro do bot ou de suas credenciais.
- Validação de conectividade.
- Configuração do chat de destino.
- Envio de mensagem de teste.
- Ativação e desativação de notificações.
- Seleção dos eventos que devem gerar mensagens.
- Histórico de envio e falhas.

Notificações iniciais:
- Compra ou venda detectada.
- Nova execução identificada.
- Sincronização concluída.
- Falha de integração.
- Credencial inválida.
- Resumo diário de resultados.
- Alertas de variação de patrimônio, configuráveis pelo usuário.

Nunca expor o token do bot nas telas, logs ou mensagens de erro. Não aceitar destinos de chat sem um processo de validação de propriedade ou autorização.

Preparar uma interface de notificações independente do Telegram para permitir novos canais futuramente.

## 3. Arquitetura modular

Separar o sistema em módulos com interfaces bem definidas.

### Núcleo da plataforma
- Autenticação e autorização.
- Usuários e preferências.
- Configurações.
- Registro de auditoria.
- Gerenciamento de módulos.
- Agendamento de tarefas.
- Notificações.
- Tratamento centralizado de erros.

### Módulo Trades
- Contas e conexões de corretoras.
- Sincronização.
- Ordens e execuções.
- Saldos e snapshots.
- Posições.
- Cálculo de resultados.
- Relatórios e gráficos.

### Módulo de integrações
Criar um contrato comum para todas as corretoras, incluindo operações como:

- Validar credenciais.
- Consultar saldos.
- Buscar ordens.
- Buscar execuções.
- Consultar histórico.
- Informar limites e capacidades suportadas.

Cada corretora deve implementar seu próprio adaptador. O módulo de análise não deve depender diretamente da API específica da Binance.

### Futuros módulos

A arquitetura deve permitir adicionar:
- Outras corretoras.
- Importação de operações via CSV.
- Relatórios avançados.
- Alertas personalizados.
- Acompanhamento de carteiras.
- Outras classes de ativos.
- Novos canais de notificação.

Evitar dependências entre módulos que não sejam necessárias.

## 4. Modelo de dados

Criar entidades para:

- users
- sessions
- roles e permissions
- modules
- user_module_settings
- exchange_providers
- exchange_connections
- encrypted_credentials
- sync_jobs
- sync_checkpoints
- exchange_orders
- trade_executions
- balances
- balance_snapshots
- asset_prices
- positions
- realized_pnl_records
- notification_channels
- notification_preferences
- notification_events
- audit_logs

Utilizar chaves primárias, chaves estrangeiras, índices e restrições de unicidade.

Toda entidade pertencente a um usuário deve possuir um vínculo explícito com ele, diretamente ou por uma relação validada pelo backend.

Nas execuções, estabelecer uma chave de idempotência baseada na corretora, conexão e identificador externo da execução, com estratégia alternativa documentada quando a corretora não fornecer um identificador confiável.

Armazenar valores financeiros com precisão decimal adequada. Não usar ponto flutuante binário para valores monetários.

Registrar datas em UTC e converter para o fuso horário do usuário na apresentação.

## 5. Segurança obrigatória

### Proteção de credenciais

- Nunca armazenar chaves de API em texto puro.
- Criptografar credenciais com criptografia autenticada, como AES-256-GCM, usando uma biblioteca consolidada.
- Manter as chaves de criptografia fora do banco de dados.
- Obter a chave mestra por um gerenciador de segredos ou mecanismo equivalente protegido.
- Permitir rotação de chaves com versionamento.
- Não incluir segredos em código, imagens Docker, arquivos versionados ou logs.
- Restringir o acesso às credenciais ao componente que efetivamente precisa delas.
- Nunca enviar segredos ao frontend depois do cadastro.
- Não permitir acesso administrativo irrestrito às credenciais em texto puro.

Utilizar permissões mínimas nas corretoras e recomendar restrição por IP quando suportada.

### Segurança da aplicação

- HTTPS obrigatório em produção.
- Cookies de sessão com Secure, HttpOnly e SameSite apropriados.
- Proteção contra CSRF quando aplicável.
- Mitigação de XSS, SQL injection e falhas de autorização.
- Rate limiting para login e endpoints sensíveis.
- Validação de entrada no servidor.
- Senhas armazenadas com algoritmo específico para hashing de senhas, como Argon2id.
- Gestão segura de sessões e tokens.
- Proteção contra tentativas repetidas de login.
- Auditoria de alterações de credenciais e configurações.
- Dependências atualizadas e verificadas.
- Backups criptografados.
- Testes automatizados de isolamento entre usuários.
- Política de retenção e exclusão de dados.

Não registrar tokens, chaves, senhas, cabeçalhos de autenticação ou conteúdo sensível em logs.

## 6. Stack tecnológica proposta

Utilizar uma stack pequena e amplamente suportada.

- Frontend: React com TypeScript.
- Interface: biblioteca de componentes acessíveis e responsivos.
- Backend: Python com FastAPI.
- Banco de dados: PostgreSQL.
- ORM e migrações: SQLAlchemy e Alembic.
- Worker: processo separado usando o mesmo código-base.
- Fila: PostgreSQL inicialmente, com Redis e uma fila dedicada quando necessário.
- Execução: Docker Compose.
- Proxy reverso: compatível com Traefik.
- Testes: pytest para backend e testes de interface.
- Documentação: OpenAPI para a API interna.

Manter frontend e backend separados logicamente, mas dentro de um monorepositório inicialmente.

Não adotar microsserviços, Kubernetes ou múltiplos bancos sem uma justificativa concreta de escala ou operação.

## 7. Interface

Criar uma interface minimalista, profissional e fácil de entender.

Menu lateral:
- Visão geral.
- Trades.
- Operações.
- Carteiras e saldos.
- Relatórios.
- Integrações.
- Notificações.
- Configurações.

Cada módulo deve ter suas próprias páginas, rotas e permissões.

Utilizar gráficos claros, tabelas com filtros, indicadores objetivos e estados vazios explicativos.

Oferecer suporte a desktop e dispositivos móveis, acessibilidade básica e feedback visual durante carregamentos, sincronizações e erros.

Não exibir todas as funcionalidades de uma só vez. Priorizar as tarefas frequentes e permitir que o usuário descubra recursos adicionais gradualmente.

## 8. Operação e observabilidade

Implementar:
- Logs estruturados.
- Métricas de sincronização.
- Monitoramento de falhas.
- Estado de saúde da API, banco e worker.
- Alertas para falhas repetidas.
- Retentativas com backoff exponencial e limites.
- Timeout para chamadas externas.
- Tratamento de limites de requisição.
- Migrações controladas de banco.
- Backup periódico e teste de restauração.

Uma falha na API de uma corretora não deve indisponibilizar o restante da plataforma.

## 9. Estratégia de testes

Criar testes para:
- Cadastro e autenticação.
- Isolamento entre usuários.
- Permissões e sessões.
- Criptografia e acesso a credenciais.
- Idempotência da sincronização.
- Paginação e recuperação após falhas.
- Tratamento de limites da API.
- Cálculo de taxas e P&L.
- Depósitos, retiradas e transferências.
- Reconciliação de saldos.
- Envio de notificações.
- Migrações e restauração de backup.

Utilizar respostas simuladas das corretoras nos testes automatizados. Não exigir chaves reais para executar a suíte de testes.

## 10. Fases de desenvolvimento

Fase 1 — Fundação:
- Estrutura do projeto.
- Login e usuários.
- Banco de dados.
- Segurança básica.
- Layout e navegação.
- Sistema de módulos.

Fase 2 — Integração:
- Cadastro de conexões.
- Cofre de credenciais.
- Adaptador Binance.
- Sincronização incremental.
- Saldos e execuções.

Fase 3 — Análise:
- Histórico de operações.
- Posições.
- P&L realizado e não realizado.
- Filtros e gráficos.
- Snapshots de patrimônio.

Fase 4 — Notificações:
- Telegram.
- Eventos.
- Resumo diário.
- Histórico de notificações.

Fase 5 — Produção:
- Auditoria.
- Monitoramento.
- Backups e restauração.
- Revisão de segurança.
- Testes de carga.
- Documentação de implantação.

## 11. Critérios de aceite

O projeto será considerado funcional quando:

1. Um usuário puder se cadastrar e utilizar sua própria conta.
2. Nenhum usuário conseguir consultar dados de outro usuário.
3. Uma conexão Binance puder ser validada e sincronizada em modo somente leitura.
4. As execuções não forem duplicadas após sincronizações repetidas.
5. Os saldos e resultados apresentarem metodologia e origem identificáveis.
6. Os filtros por data, ativo e corretora funcionarem.
7. O Telegram enviar mensagens para um destino validado.
8. Nenhuma credencial aparecer no frontend, logs ou respostas de erro.
9. O sistema se recuperar de falhas temporárias da corretora.
10. Um novo módulo puder ser adicionado sem reescrever o núcleo.
11. A aplicação puder ser instalada por Docker Compose.
12. Os backups puderem ser restaurados e validados.

## 12. Instruções para a IA de desenvolvimento

Antes de implementar:
1. Apresente a arquitetura e a árvore de diretórios.
2. Defina os contratos entre os módulos.
3. Documente o modelo de dados e as principais decisões de segurança.
4. Apresente o plano de implementação por fases.

Em seguida, desenvolva cada fase de forma incremental, com código executável, migrações, testes, arquivos de configuração de exemplo e documentação.

Não entregar apenas telas demonstrativas. Toda funcionalidade apresentada deve estar ligada ao backend e aos dados reais ou identificada explicitamente como demonstração.

Não inventar resultados financeiros, não simular integrações reais sem avisar e não armazenar segredos em arquivos de exemplo.

Priorizar simplicidade, legibilidade, testes, segurança e evolução gradual.