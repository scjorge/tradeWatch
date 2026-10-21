import { Alert, Button, Card, Group, Modal, PasswordInput, Select, SimpleGrid, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NumberInput } from "@mantine/core";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { PageHeader } from "../components/common";
import { CURRENCY_OPTIONS } from "../lib/currency";
import { useModuleSettings } from "../lib/moduleSettings";
import { fmtDate } from "../lib/format";

interface SessionRow {
  id: string;
  created_at: string;
  last_seen_at: string;
  ip: string | null;
  user_agent: string | null;
  current: boolean;
}

const PRICE_REFRESH_OPTIONS = [
  { value: "0", label: "Desligada" },
  { value: "5", label: "A cada 5 segundos" },
  { value: "10", label: "A cada 10 segundos" },
  { value: "15", label: "A cada 15 segundos" },
  { value: "30", label: "A cada 30 segundos" },
  { value: "60", label: "A cada 1 minuto" },
  { value: "120", label: "A cada 2 minutos" },
  { value: "300", label: "A cada 5 minutos" },
];

const TIMEZONES = ["America/Sao_Paulo", "America/Manaus", "America/Fortaleza", "America/Noronha", "America/New_York", "Europe/Lisbon", "Europe/London", "UTC"];

function Profile() {
  const { user, refresh } = useAuth();
  const qc = useQueryClient();
  const [form, setForm] = useState({ display_name: "", timezone: "", base_currency: "", cost_method: "", price_refresh_seconds: 60 });
  useEffect(() => {
    if (user) setForm({ display_name: user.display_name, timezone: user.timezone, base_currency: user.base_currency, cost_method: user.cost_method, price_refresh_seconds: user.price_refresh_seconds });
  }, [user]);
  const save = useMutation({
    mutationFn: () => api<User>("/api/me", { method: "PATCH", body: form }),
    onSuccess: () => {
      void refresh();
      void qc.invalidateQueries();
      notifications.show({ color: "teal", message: "Preferências salvas. Resultados recalculados." });
    },
    onError: (e: Error) => notifications.show({ color: "red", message: e.message }),
  });
  return (
    <Card withBorder radius="md">
      <Title order={5} mb="sm">Perfil e preferências</Title>
      <Stack>
        <TextInput label="Nome" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.currentTarget.value })} />
        <TextInput label="E-mail" value={user?.email ?? ""} disabled />
        <Select label="Fuso horário" data={Array.from(new Set([form.timezone, ...TIMEZONES])).filter(Boolean)} value={form.timezone} onChange={(v) => v && setForm({ ...form, timezone: v })} searchable />
        <Select
          label="Moeda padrão da plataforma"
          description="Moeda em que patrimônio, resultados e operações são exibidos. Dólar usa USDT, a referência de dólar nas corretoras. Ao trocar, tudo é recalculado com o câmbio histórico de cada operação."
          data={CURRENCY_OPTIONS}
          value={form.base_currency}
          onChange={(v) => v && setForm({ ...form, base_currency: v })}
          allowDeselect={false}
        />
        <Select
          label="Método de apuração de custo"
          data={[
            { value: "FIFO", label: "FIFO — primeiro a entrar, primeiro a sair" },
            { value: "AVERAGE", label: "Custo médio ponderado" },
          ]}
          value={form.cost_method}
          onChange={(v) => v && setForm({ ...form, cost_method: v })}
        />
        <Select
          label="Atualização automática de cotações"
          description="Com que frequência a tela de Operações atualiza as cotações das posições em aberto, enquanto estiver aberta."
          data={PRICE_REFRESH_OPTIONS}
          value={String(form.price_refresh_seconds)}
          onChange={(v) => v !== null && setForm({ ...form, price_refresh_seconds: Number(v) })}
          allowDeselect={false}
        />
        <Group justify="flex-end">
          <Button onClick={() => save.mutate()} loading={save.isPending}>Salvar</Button>
        </Group>
      </Stack>
    </Card>
  );
}

function HideSmallBalances() {
  const prefs = useModuleSettings("trades");
  const saved = Number(prefs.settings?.hide_price_below_usd ?? 0) || 0;
  const [value, setValue] = useState<number | string>(0);
  useEffect(() => setValue(saved), [saved]);
  return (
    <Card withBorder radius="md">
      <Title order={5} mb="sm">Ativos de baixo valor</Title>
      <Stack>
        <NumberInput
          label="Ocultar ativos com valor unitário menor que (US$)"
          description="Esconde ativos cujo preço de 1 unidade (cotação de venda) é menor que este valor em dólar, independentemente da quantidade que você tem. Vale em Carteiras e saldos e, em Operações, nas ordens ainda não concluídas (as concluídas permanecem). Use 0 para mostrar todos. Ativos sem cotação continuam visíveis."
          min={0}
          decimalScale={2}
          prefix="US$ "
          value={value}
          onChange={setValue}
        />
        <Group justify="flex-end">
          <Button disabled={!prefs.loaded} onClick={() => { prefs.save({ hide_price_below_usd: Number(value) || 0 }); notifications.show({ color: "teal", message: "Preferência salva." }); }}>Salvar</Button>
        </Group>
      </Stack>
    </Card>
  );
}

function ChangePassword() {
  const [f, setF] = useState({ current: "", next: "", confirm: "" });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const m = useMutation({
    mutationFn: () => api("/api/me/password", { body: { current_password: f.current, new_password: f.next } }),
    onSuccess: () => { setMsg({ ok: true, text: "Senha alterada. As outras sessões foram encerradas." }); setF({ current: "", next: "", confirm: "" }); },
    onError: (e: Error) => setMsg({ ok: false, text: e.message }),
  });
  return (
    <Card withBorder radius="md">
      <Title order={5} mb="sm">Alterar senha</Title>
      <form onSubmit={(e) => { e.preventDefault(); if (f.next !== f.confirm) return setMsg({ ok: false, text: "As senhas não coincidem." }); m.mutate(); }}>
        <Stack>
          {msg && <Alert color={msg.ok ? "teal" : "red"}>{msg.text}</Alert>}
          <PasswordInput label="Senha atual" required autoComplete="current-password" value={f.current} onChange={(e) => setF({ ...f, current: e.currentTarget.value })} />
          <PasswordInput label="Nova senha" required autoComplete="new-password" value={f.next} onChange={(e) => setF({ ...f, next: e.currentTarget.value })} />
          <PasswordInput label="Confirme" required autoComplete="new-password" value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.currentTarget.value })} />
          <Group justify="flex-end"><Button type="submit" loading={m.isPending}>Alterar senha</Button></Group>
        </Stack>
      </form>
      <Text size="xs" c="dimmed" mt="sm">Autenticação em dois fatores (TOTP) está preparada no backend e será habilitada em uma próxima versão.</Text>
    </Card>
  );
}

function DeleteAccount() {
  const { logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const del = useMutation({
    mutationFn: () => api("/api/me/delete", { method: "POST", body: { password } }),
    onSuccess: () => void logout().catch(() => window.location.assign("/")),
    onError: (e: Error) => setError(e.message),
  });
  const close = () => { setOpen(false); setPassword(""); setError(null); };
  return (
    <Card withBorder radius="md" mt="md" style={{ borderColor: "var(--mantine-color-red-6)" }}>
      <Group justify="space-between" wrap="nowrap">
        <div>
          <Title order={5}>Excluir conta</Title>
          <Text size="sm" c="dimmed">Apaga seu usuário e todos os dados: integrações, operações, resultados e notificações. Não há como desfazer.</Text>
        </div>
        <Button color="red" variant="light" onClick={() => setOpen(true)}>Excluir minha conta</Button>
      </Group>
      <Modal opened={open} onClose={close} title="Excluir conta definitivamente" centered>
        <form onSubmit={(e) => { e.preventDefault(); setError(null); del.mutate(); }}>
          <Stack>
            <Alert color="red">Todos os seus dados serão apagados permanentemente. As chaves da Binance cadastradas serão removidas daqui (revogue-as também na Binance).</Alert>
            {error && <Alert color="red" variant="outline">{error}</Alert>}
            <PasswordInput label="Confirme sua senha" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.currentTarget.value)} data-autofocus />
            <Group justify="flex-end">
              <Button variant="default" onClick={close}>Cancelar</Button>
              <Button type="submit" color="red" loading={del.isPending} disabled={!password}>Excluir definitivamente</Button>
            </Group>
          </Stack>
        </form>
      </Modal>
    </Card>
  );
}

function Sessions() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["sessions"], queryFn: () => api<SessionRow[]>("/api/me/sessions") });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["sessions"] });
  return (
    <Card withBorder radius="md">
      <Group justify="space-between" mb="sm">
        <Title order={5}>Sessões ativas</Title>
        <Button size="xs" variant="light" color="red" onClick={() => api("/api/me/sessions/revoke-others", { method: "POST" }).then(refresh)}>Encerrar as outras</Button>
      </Group>
      <Table.ScrollContainer minWidth={600}>
        <Table fz="sm">
          <Table.Thead><Table.Tr><Table.Th>Dispositivo</Table.Th><Table.Th>IP</Table.Th><Table.Th>Último acesso</Table.Th><Table.Th /></Table.Tr></Table.Thead>
          <Table.Tbody>
            {q.data?.map((s) => (
              <Table.Tr key={s.id}>
                <Table.Td><Text size="xs" lineClamp={1} maw={300}>{s.user_agent ?? "—"}</Text></Table.Td>
                <Table.Td>{s.ip ?? "—"}</Table.Td>
                <Table.Td>{fmtDate(s.last_seen_at, user?.timezone)}</Table.Td>
                <Table.Td>{s.current ? <Text size="xs" c="teal">esta sessão</Text> : <Button size="compact-xs" variant="subtle" color="red" onClick={() => api(`/api/me/sessions/${s.id}`, { method: "DELETE" }).then(refresh)}>Encerrar</Button>}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Card>
  );
}

export function SettingsPage() {
  return (
    <>
      <PageHeader title="Configurações" />
      <SimpleGrid cols={{ base: 1, lg: 2 }} mb="md">
        <Profile />
        <ChangePassword />
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, lg: 2 }} mb="md">
        <HideSmallBalances />
      </SimpleGrid>
      <Sessions />
      <DeleteAccount />
    </>
  );
}
