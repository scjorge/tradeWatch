import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Code,
  Drawer,
  Group,
  List,
  Modal,
  PasswordInput,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  TagsInput,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconKey, IconPlayerPause, IconPlayerPlay, IconPlus, IconRefresh, IconShieldCheck, IconTrash } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { Connection, Paged, Provider, SyncJob } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, InfoNote, Loading, PageHeader, StatusBadge } from "../components/common";
import { fmtDate, relative } from "../lib/format";

type Validation = { ok: boolean; message: string; warnings: string[] };

function useInvalidate() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["connections"] });
    void qc.invalidateQueries({ queryKey: ["jobs"] });
    void qc.invalidateQueries({ queryKey: ["dashboard"] });
  };
}

function notifyValidation(v: Validation) {
  notifications.show({ color: v.ok ? "teal" : "red", title: v.ok ? "Conexão validada" : "Falha na validação", message: [v.message, ...v.warnings].join(" ") });
}

function CredentialFields({ provider, values, onChange }: { provider: Provider; values: Record<string, string>; onChange: (v: Record<string, string>) => void }) {
  return (
    <>
      {provider.credential_fields.map((f) =>
        f.secret ? (
          <PasswordInput key={f.name} label={f.label} description={f.help} required autoComplete="off" value={values[f.name] ?? ""} onChange={(e) => onChange({ ...values, [f.name]: e.currentTarget.value })} />
        ) : (
          <TextInput key={f.name} label={f.label} description={f.help} required autoComplete="off" spellCheck={false} value={values[f.name] ?? ""} onChange={(e) => onChange({ ...values, [f.name]: e.currentTarget.value })} />
        ),
      )}
    </>
  );
}

function Instructions({ provider }: { provider: Provider }) {
  return (
    <Alert color="blue" variant="light" icon={<IconShieldCheck />} title={`Como criar a chave na ${provider.name}`}>
      <List type="ordered" size="sm" spacing={4}>
        {provider.instructions.map((s, i) => (
          <List.Item key={i}>{s}</List.Item>
        ))}
      </List>
      {provider.docs_url && (
        <Anchor href={provider.docs_url} target="_blank" rel="noreferrer noopener" size="sm" mt={6} display="block">
          Guia oficial da {provider.name}
        </Anchor>
      )}
    </Alert>
  );
}

function AddConnectionModal({ opened, onClose, providers }: { opened: boolean; onClose: () => void; providers: Provider[] }) {
  const invalidate = useInvalidate();
  const [providerKey, setProviderKey] = useState<string | null>(providers[0]?.key ?? null);
  const [name, setName] = useState("");
  const [creds, setCreds] = useState<Record<string, string>>({});
  const [symbols, setSymbols] = useState<string[]>([]);
  const [historyStart, setHistoryStart] = useState("");
  const [error, setError] = useState<string | null>(null);
  const provider = providers.find((p) => p.key === providerKey);

  const create = useMutation({
    mutationFn: () =>
      api<{ connection: Connection; validation: Validation }>("/api/integrations/connections", {
        body: { provider: providerKey, name, credentials: creds, settings: { extra_symbols: symbols, ...(historyStart ? { history_start: historyStart } : {}) } },
      }),
    onSuccess: (r) => {
      notifyValidation(r.validation);
      setCreds({});
      setName("");
      invalidate();
      onClose();
    },
    onError: (e: ApiError) => setError(e.message),
  });

  return (
    <Modal opened={opened} onClose={() => { setCreds({}); onClose(); }} title="Nova integração" size="lg">
      <form onSubmit={(e) => { e.preventDefault(); setError(null); create.mutate(); }}>
        <Stack>
          <Select label="Corretora" data={providers.map((p) => ({ value: p.key, label: p.name }))} value={providerKey} onChange={setProviderKey} allowDeselect={false} />
          {provider && <Instructions provider={provider} />}
          <TextInput label="Nome amigável" placeholder="ex.: Binance principal" required maxLength={80} value={name} onChange={(e) => setName(e.currentTarget.value)} />
          {provider && <CredentialFields provider={provider} values={creds} onChange={setCreds} />}
          <TagsInput
            label="Pares adicionais (opcional)"
            description="Pares de ativos que você já zerou e quer incluir no histórico, ex.: ETHUSDT, SOLBRL."
            value={symbols}
            onChange={(v) => setSymbols(v.map((s) => s.toUpperCase().replace("/", "")))}
            clearable
          />
          <TextInput label="Buscar depósitos/retiradas desde (opcional)" placeholder="AAAA-MM-DD" value={historyStart} onChange={(e) => setHistoryStart(e.currentTarget.value)} />
          {error && <Alert color="red">{error}</Alert>}
          <Text size="xs" c="dimmed">
            A chave secreta é cifrada (AES-256-GCM) antes de ser gravada e nunca mais é exibida. A conexão é validada antes de ser ativada.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>Cancelar</Button>
            <Button type="submit" loading={create.isPending}>Validar e salvar</Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function ReplaceCredentialsModal({ conn, provider, opened, onClose }: { conn: Connection; provider?: Provider; opened: boolean; onClose: () => void }) {
  const invalidate = useInvalidate();
  const [creds, setCreds] = useState<Record<string, string>>({});
  const m = useMutation({
    mutationFn: () => api<{ validation: Validation }>(`/api/integrations/connections/${conn.id}/credentials`, { method: "PUT", body: { credentials: creds } }),
    onSuccess: (r) => { notifyValidation(r.validation); setCreds({}); invalidate(); onClose(); },
    onError: (e: Error) => notifications.show({ color: "red", message: e.message }),
  });
  if (!provider) return null;
  return (
    <Modal opened={opened} onClose={onClose} title="Substituir credencial" size="lg">
      <form onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
        <Stack>
          <Text size="sm" c="dimmed">Informe a nova chave. A credencial atual não pode ser exibida nem recuperada.</Text>
          <Instructions provider={provider} />
          <CredentialFields provider={provider} values={creds} onChange={setCreds} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>Cancelar</Button>
            <Button type="submit" loading={m.isPending}>Validar e substituir</Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function ConnectionDrawer({ conn, provider, onClose }: { conn: Connection; provider?: Provider; onClose: () => void }) {
  const { user } = useAuth();
  const invalidate = useInvalidate();
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [credsOpen, setCredsOpen] = useState(false);
  const [symbols, setSymbols] = useState<string[]>(conn.settings.extra_symbols ?? []);
  const jobs = useQuery({
    queryKey: ["jobs", conn.id, onlyErrors],
    queryFn: () => api<Paged<SyncJob>>(`/api/integrations/connections/${conn.id}/jobs?page_size=30&only_errors=${onlyErrors}`),
    refetchInterval: conn.current_job ? 4000 : false,
  });
  const action = (path: string, okMsg: string) =>
    api(`/api/integrations/connections/${conn.id}/${path}`, { method: "POST" })
      .then((r) => {
        const v = (r as { validation?: Validation }).validation;
        if (v) notifyValidation(v);
        else notifications.show({ color: "teal", message: okMsg });
        invalidate();
      })
      .catch((e: Error) => notifications.show({ color: "red", message: e.message }));

  const saveSettings = () =>
    api(`/api/integrations/connections/${conn.id}`, { method: "PATCH", body: { settings: { ...conn.settings, extra_symbols: symbols } } })
      .then(() => { notifications.show({ color: "teal", message: "Configurações salvas." }); invalidate(); })
      .catch((e: Error) => notifications.show({ color: "red", message: e.message }));

  const remove = () =>
    modals.openConfirmModal({
      title: "Remover conexão",
      children: <Text size="sm">A conexão, a credencial cifrada e todos os dados sincronizados dela serão apagados. Essa ação não pode ser desfeita.</Text>,
      labels: { confirm: "Remover", cancel: "Cancelar" },
      confirmProps: { color: "red" },
      onConfirm: () =>
        api(`/api/integrations/connections/${conn.id}`, { method: "DELETE" }).then(() => {
          notifications.show({ message: "Conexão removida." });
          invalidate();
          onClose();
        }),
    });

  const suspended = conn.status === "suspended";
  return (
    <Drawer opened onClose={onClose} position="right" size="xl" title={<Title order={4}>{conn.name}</Title>}>
      <Stack>
        <Group>
          <StatusBadge status={conn.status} />
          {conn.current_job && <Badge variant="dot">Sincronização {conn.current_job.status === "running" ? "em andamento" : "na fila"}</Badge>}
        </Group>
        {conn.status_message && <Alert color={conn.status === "active" ? "blue" : "orange"} icon={<IconAlertTriangle />}>{conn.status_message}</Alert>}
        <SimpleGrid cols={2} spacing="xs">
          <Text size="sm" c="dimmed">Corretora</Text><Text size="sm">{conn.provider_name}</Text>
          <Text size="sm" c="dimmed">Credencial</Text><Text size="sm">API key <Code>{conn.credential_hint ?? "—"}</Code> · atualizada {relative(conn.credential_updated_at)}</Text>
          <Text size="sm" c="dimmed">Última sincronização</Text><Text size="sm">{fmtDate(conn.last_successful_sync_at, user?.timezone)}</Text>
          <Text size="sm" c="dimmed">Última tentativa</Text><Text size="sm">{fmtDate(conn.last_sync_at, user?.timezone)}</Text>
          <Text size="sm" c="dimmed">Falhas seguidas</Text><Text size="sm">{conn.consecutive_failures}</Text>
        </SimpleGrid>
        <Group gap="xs">
          <Button size="xs" leftSection={<IconRefresh size={14} />} disabled={suspended || conn.status === "invalid_credentials"} onClick={() => action("sync", "Sincronização agendada.")}>
            Sincronizar agora
          </Button>
          <Button size="xs" variant="light" leftSection={<IconShieldCheck size={14} />} disabled={suspended} onClick={() => action("validate", "Validada.")}>
            Validar
          </Button>
          <Button size="xs" variant="light" leftSection={<IconKey size={14} />} onClick={() => setCredsOpen(true)}>
            Substituir credencial
          </Button>
          {suspended ? (
            <Button size="xs" variant="light" color="teal" leftSection={<IconPlayerPlay size={14} />} onClick={() => action("resume", "Conexão reativada.")}>Reativar</Button>
          ) : (
            <Button size="xs" variant="light" color="gray" leftSection={<IconPlayerPause size={14} />} onClick={() => action("suspend", "Conexão suspensa.")}>Suspender</Button>
          )}
          <Button size="xs" variant="subtle" color="red" leftSection={<IconTrash size={14} />} onClick={remove}>Remover</Button>
        </Group>

        <Card withBorder>
          <Title order={6} mb="xs">Pares adicionais</Title>
          <Text size="xs" c="dimmed" mb="xs">
            A Binance exige consultar execuções por par. Os pares dos ativos em carteira são descobertos automaticamente; inclua aqui pares já zerados.
          </Text>
          <Group align="flex-end">
            <TagsInput value={symbols} onChange={(v) => setSymbols(v.map((s) => s.toUpperCase().replace("/", "")))} placeholder="ex.: ETHUSDT" style={{ flex: 1 }} />
            <Button size="xs" variant="light" onClick={saveSettings}>Salvar</Button>
          </Group>
        </Card>

        <Group justify="space-between">
          <Title order={6}>Histórico de sincronizações</Title>
          <Switch size="xs" label="Somente erros" checked={onlyErrors} onChange={(e) => setOnlyErrors(e.currentTarget.checked)} />
        </Group>
        {jobs.isLoading ? (
          <Loading />
        ) : (
          <Table.ScrollContainer minWidth={600}>
            <Table fz="xs" striped>
              <Table.Thead>
                <Table.Tr><Table.Th>Criada</Table.Th><Table.Th>Origem</Table.Th><Table.Th>Estado</Table.Th><Table.Th>Tentativas</Table.Th><Table.Th>Detalhes</Table.Th></Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {jobs.data?.items.map((j) => (
                  <Table.Tr key={j.id}>
                    <Table.Td>{fmtDate(j.created_at, user?.timezone)}</Table.Td>
                    <Table.Td>{{ manual: "Manual", schedule: "Agendada", initial: "Inicial" }[j.trigger] ?? j.trigger}</Table.Td>
                    <Table.Td><StatusBadge status={j.status} /></Table.Td>
                    <Table.Td>{j.attempts}</Table.Td>
                    <Table.Td>
                      {j.error_message ? (
                        <Text size="xs" c="red">{j.error_message}{j.status === "queued" && ` · nova tentativa ${fmtDate(j.run_after, user?.timezone)}`}</Text>
                      ) : j.status === "succeeded" ? (
                        <Text size="xs" c="dimmed">{j.stats.executions_new ?? 0} execução(ões) nova(s) · {j.stats.symbols ?? 0} par(es) · {j.stats.duration_seconds ?? "?"}s</Text>
                      ) : null}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
        {provider && (
          <InfoNote>
            <Text size="xs" fw={600}>Capacidades desta integração</Text>
            <List size="xs">{provider.capabilities.notes.map((n) => <List.Item key={n}>{n}</List.Item>)}<List.Item>Limites: {provider.capabilities.rate_limit}</List.Item></List>
          </InfoNote>
        )}
      </Stack>
      <ReplaceCredentialsModal conn={conn} provider={provider} opened={credsOpen} onClose={() => setCredsOpen(false)} />
    </Drawer>
  );
}

export function IntegrationsPage() {
  const { user } = useAuth();
  const [adding, setAdding] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const providers = useQuery({ queryKey: ["providers"], queryFn: () => api<Provider[]>("/api/integrations/providers") });
  const conns = useQuery({
    queryKey: ["connections"],
    queryFn: () => api<Connection[]>("/api/integrations/connections"),
    refetchInterval: (q) => ((q.state.data ?? []).some((c) => c.current_job || c.status === "syncing") ? 4000 : 30_000),
  });
  const current = conns.data?.find((c) => c.id === selected);

  return (
    <>
      <PageHeader
        title="Integrações"
        description="Conexões com corretoras em modo somente leitura. Nenhuma ordem é enviada e nenhum saque é possível."
        actions={<Button leftSection={<IconPlus size={16} />} onClick={() => setAdding(true)} disabled={!providers.data?.length}>Adicionar</Button>}
      />
      {conns.isLoading ? (
        <Loading />
      ) : !conns.data?.length ? (
        <EmptyState title="Nenhuma conexão" description="Adicione sua primeira corretora para começar a acompanhar suas operações." action={<Button onClick={() => setAdding(true)}>Adicionar integração</Button>} />
      ) : (
        <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }}>
          {conns.data.map((c) => (
            <Card key={c.id} withBorder radius="md" style={{ cursor: "pointer" }} onClick={() => setSelected(c.id)} role="button" aria-label={`Abrir ${c.name}`}>
              <Group justify="space-between" mb="xs">
                <div>
                  <Text fw={600}>{c.name}</Text>
                  <Text size="xs" c="dimmed">{c.provider_name} · chave {c.credential_hint}</Text>
                </div>
                <StatusBadge status={c.current_job?.status === "running" ? "syncing" : c.status} />
              </Group>
              <Text size="sm">Última sincronização: {relative(c.last_successful_sync_at)}</Text>
              <Text size="xs" c="dimmed">{fmtDate(c.last_successful_sync_at, user?.timezone)}</Text>
              {c.status_message && <Text size="xs" c="orange" mt={4} lineClamp={2}>{c.status_message}</Text>}
            </Card>
          ))}
        </SimpleGrid>
      )}
      {providers.data && <AddConnectionModal opened={adding} onClose={() => setAdding(false)} providers={providers.data} />}
      {current && <ConnectionDrawer conn={current} provider={providers.data?.find((p) => p.key === current.provider)} onClose={() => setSelected(null)} />}
    </>
  );
}
