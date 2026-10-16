import { Alert, Badge, Button, Card, Code, CopyButton, Group, List, Modal, NumberInput, PasswordInput, SimpleGrid, Stack, Switch, Table, Text, TextInput, Title } from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { IconBrandTelegram, IconCopy, IconPlus, IconSend, IconTrash } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Channel, Paged, Preference, VerificationPayload } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, InfoNote, Loading, PageHeader, StatusBadge } from "../components/common";
import { fmtDate } from "../lib/format";

interface EventRow {
  id: string;
  event_type: string;
  label: string;
  message: string;
  status: string;
  attempts: number;
  error: string | null;
  created_at: string;
  sent_at: string | null;
}

function VerificationBox({ payload, onVerified }: { payload: VerificationPayload; onVerified: () => void }) {
  const verify = useMutation({
    mutationFn: () => api<Channel>(`/api/notifications/channels/${payload.channel.id}/verify`, { method: "POST" }),
    onSuccess: () => { notifications.show({ color: "teal", message: "Destino verificado e canal ativado." }); onVerified(); },
    onError: (e: ApiError) => notifications.show({ color: "orange", message: e.message }),
  });
  return (
    <Stack>
      <Alert color="blue" title="Comprove que o destino é seu">
        <Group gap="xs" mb="xs">
          <Text size="sm">Código:</Text>
          <Code fz="md">{payload.verification_code}</Code>
          <CopyButton value={payload.verification_code}>
            {({ copied, copy }) => <Button size="compact-xs" variant="subtle" leftSection={<IconCopy size={12} />} onClick={copy}>{copied ? "Copiado" : "Copiar"}</Button>}
          </CopyButton>
        </Group>
        <List size="sm" spacing={4}>{payload.instructions.map((i) => <List.Item key={i}>{i}</List.Item>)}</List>
        <Text size="xs" c="dimmed" mt="xs">O código expira em {payload.expires_in_minutes} minutos.</Text>
      </Alert>
      <Button onClick={() => verify.mutate()} loading={verify.isPending}>Verificar destino</Button>
    </Stack>
  );
}

function AddTelegram({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("Telegram");
  const [token, setToken] = useState("");
  const [payload, setPayload] = useState<VerificationPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => api<VerificationPayload>("/api/notifications/channels/telegram", { body: { name, bot_token: token } }),
    onSuccess: (p) => { setPayload(p); setToken(""); void qc.invalidateQueries({ queryKey: ["channels"] }); },
    onError: (e: ApiError) => setError(e.message),
  });
  const close = () => { setPayload(null); setError(null); setToken(""); onClose(); };
  return (
    <Modal opened={opened} onClose={close} title="Conectar bot do Telegram" size="lg">
      {payload ? (
        <VerificationBox payload={payload} onVerified={() => { void qc.invalidateQueries({ queryKey: ["channels"] }); close(); }} />
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); setError(null); create.mutate(); }}>
          <Stack>
            <Alert color="gray" variant="light" title="Como criar o bot">
              <List type="ordered" size="sm" spacing={4}>
                <List.Item>No Telegram, abra uma conversa com <b>@BotFather</b> e envie <Code>/newbot</Code>.</List.Item>
                <List.Item>Escolha um nome e um usuário terminado em "bot".</List.Item>
                <List.Item>Copie o token informado pelo BotFather e cole abaixo. Ele será cifrado e nunca mais exibido.</List.Item>
                <List.Item>Para grupos, adicione o bot ao grupo depois desta etapa.</List.Item>
              </List>
            </Alert>
            <TextInput label="Nome do canal" value={name} onChange={(e) => setName(e.currentTarget.value)} required maxLength={80} />
            <PasswordInput label="Token do bot" required autoComplete="off" value={token} onChange={(e) => setToken(e.currentTarget.value.trim())} />
            {error && <Alert color="red">{error}</Alert>}
            <Group justify="flex-end">
              <Button variant="default" onClick={close}>Cancelar</Button>
              <Button type="submit" loading={create.isPending}>Validar bot</Button>
            </Group>
          </Stack>
        </form>
      )}
    </Modal>
  );
}

function ChannelCard({ ch }: { ch: Channel }) {
  const qc = useQueryClient();
  const [verifying, setVerifying] = useState<VerificationPayload | null>(null);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["channels"] });
  const call = (p: Promise<unknown>, ok: string) => p.then(() => { notifications.show({ color: "teal", message: ok }); refresh(); void qc.invalidateQueries({ queryKey: ["notif-events"] }); }).catch((e: Error) => notifications.show({ color: "red", message: e.message }));
  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb="xs">
        <Group gap="xs">
          <IconBrandTelegram size={20} />
          <div>
            <Text fw={600}>{ch.name}</Text>
            <Text size="xs" c="dimmed">@{ch.bot_username} · token …{ch.token_hint}</Text>
          </div>
        </Group>
        <StatusBadge status={ch.status} />
      </Group>
      {ch.chat_title && <Text size="sm">Destino: {ch.chat_title} <Badge size="xs" variant="light">{ch.chat_type}</Badge></Text>}
      {ch.last_error && <Text size="xs" c="red">Último erro: {ch.last_error}</Text>}
      <Group mt="sm" gap="xs">
        {ch.status === "active" ? (
          <>
            <Switch label="Ativo" checked={ch.enabled} onChange={(e) => call(api(`/api/notifications/channels/${ch.id}`, { method: "PATCH", body: { enabled: e.currentTarget.checked } }), "Canal atualizado.")} />
            <Button size="xs" variant="light" leftSection={<IconSend size={14} />} onClick={() => call(api(`/api/notifications/channels/${ch.id}/test`, { method: "POST" }), "Mensagem de teste enviada.")}>Enviar teste</Button>
          </>
        ) : (
          <Button size="xs" onClick={() => api<VerificationPayload>(`/api/notifications/channels/${ch.id}/verification-code`, { method: "POST" }).then(setVerifying)}>Verificar destino</Button>
        )}
        <Button
          size="xs"
          variant="subtle"
          color="red"
          leftSection={<IconTrash size={14} />}
          onClick={() =>
            modals.openConfirmModal({
              title: "Remover canal",
              children: <Text size="sm">O token cifrado será apagado.</Text>,
              labels: { confirm: "Remover", cancel: "Cancelar" },
              confirmProps: { color: "red" },
              onConfirm: () => call(api(`/api/notifications/channels/${ch.id}`, { method: "DELETE" }), "Canal removido."),
            })
          }
        >
          Remover
        </Button>
      </Group>
      <Modal opened={!!verifying} onClose={() => setVerifying(null)} title="Verificar destino">
        {verifying && <VerificationBox payload={verifying} onVerified={() => { setVerifying(null); refresh(); }} />}
      </Modal>
    </Card>
  );
}

function Preferences() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["prefs"], queryFn: () => api<Preference[]>("/api/notifications/preferences") });
  const [items, setItems] = useState<Preference[]>([]);
  useEffect(() => { if (q.data) setItems(q.data); }, [q.data]);
  const save = useMutation({
    mutationFn: () => api<Preference[]>("/api/notifications/preferences", { method: "PUT", body: { items: items.map(({ event_type, enabled, settings }) => ({ event_type, enabled, settings })) } }),
    onSuccess: (d) => { qc.setQueryData(["prefs"], d); notifications.show({ color: "teal", message: "Preferências salvas." }); },
    onError: (e: Error) => notifications.show({ color: "red", message: e.message }),
  });
  if (q.isLoading) return <Loading />;
  const set = (i: number, p: Partial<Preference>) => setItems(items.map((x, j) => (j === i ? { ...x, ...p } : x)));
  return (
    <Card withBorder radius="md">
      <Title order={5} mb="sm">Eventos que geram mensagens</Title>
      <Stack gap="sm">
        {items.map((p, i) => (
          <Group key={p.event_type} justify="space-between" wrap="wrap">
            <Switch label={p.label} checked={p.enabled} onChange={(e) => set(i, { enabled: e.currentTarget.checked })} />
            {p.event_type === "daily_summary" && (
              <NumberInput size="xs" w={150} label="Hora (seu fuso)" min={0} max={23} value={p.settings.hour} onChange={(v) => set(i, { settings: { ...p.settings, hour: Number(v) } })} />
            )}
            {p.event_type === "equity_change" && (
              <NumberInput size="xs" w={150} label="Variação mínima (%)" min={0.1} max={100} step={0.5} decimalScale={2} value={p.settings.threshold_pct} onChange={(v) => set(i, { settings: { ...p.settings, threshold_pct: Number(v) } })} />
            )}
          </Group>
        ))}
      </Stack>
      <Group justify="flex-end" mt="md">
        <Button onClick={() => save.mutate()} loading={save.isPending}>Salvar preferências</Button>
      </Group>
    </Card>
  );
}

function History() {
  const { user } = useAuth();
  const q = useQuery({ queryKey: ["notif-events"], queryFn: () => api<Paged<EventRow>>("/api/notifications/events?page_size=50"), refetchInterval: 30_000 });
  if (q.isLoading) return <Loading />;
  if (!q.data?.total) return <Text size="sm" c="dimmed">Nenhuma notificação enviada ainda.</Text>;
  return (
    <Table.ScrollContainer minWidth={700}>
      <Table fz="sm" striped>
        <Table.Thead><Table.Tr><Table.Th>Data</Table.Th><Table.Th>Evento</Table.Th><Table.Th>Mensagem</Table.Th><Table.Th>Estado</Table.Th></Table.Tr></Table.Thead>
        <Table.Tbody>
          {q.data.items.map((e) => (
            <Table.Tr key={e.id}>
              <Table.Td>{fmtDate(e.created_at, user?.timezone)}</Table.Td>
              <Table.Td>{e.label}</Table.Td>
              <Table.Td><Text size="xs" lineClamp={2} maw={420}>{e.message}</Text>{e.error && <Text size="xs" c="red">{e.error}</Text>}</Table.Td>
              <Table.Td><StatusBadge status={e.status} /></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

export function NotificationsPage() {
  const [adding, setAdding] = useState(false);
  const channels = useQuery({ queryKey: ["channels"], queryFn: () => api<Channel[]>("/api/notifications/channels") });
  return (
    <>
      <PageHeader title="Notificações" description="Receba alertas de operações, sincronizações e resultados." actions={<Button leftSection={<IconPlus size={16} />} onClick={() => setAdding(true)}>Conectar Telegram</Button>} />
      <InfoNote>Um destino só é aceito depois que você envia o código de verificação ao bot pelo próprio chat ou grupo.</InfoNote>
      {channels.isLoading ? (
        <Loading />
      ) : !channels.data?.length ? (
        <EmptyState title="Nenhum canal" description="Conecte um bot do Telegram para receber notificações." action={<Button onClick={() => setAdding(true)}>Conectar Telegram</Button>} />
      ) : (
        <SimpleGrid cols={{ base: 1, md: 2 }} mb="md">
          {channels.data.map((c) => <ChannelCard key={c.id} ch={c} />)}
        </SimpleGrid>
      )}
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Preferences />
        <Card withBorder radius="md">
          <Title order={5} mb="sm">Histórico de envios</Title>
          <History />
        </Card>
      </SimpleGrid>
      <AddTelegram opened={adding} onClose={() => setAdding(false)} />
    </>
  );
}
