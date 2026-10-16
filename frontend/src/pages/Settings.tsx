import { Alert, Button, Card, Group, PasswordInput, Select, SimpleGrid, Stack, Table, Text, TextInput, Title } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { PageHeader } from "../components/common";
import { fmtDate } from "../lib/format";

interface SessionRow {
  id: string;
  created_at: string;
  last_seen_at: string;
  ip: string | null;
  user_agent: string | null;
  current: boolean;
}

const TIMEZONES = ["America/Sao_Paulo", "America/Manaus", "America/Fortaleza", "America/Noronha", "America/New_York", "Europe/Lisbon", "Europe/London", "UTC"];

function Profile() {
  const { user, refresh } = useAuth();
  const qc = useQueryClient();
  const [form, setForm] = useState({ display_name: "", timezone: "", base_currency: "", cost_method: "" });
  useEffect(() => {
    if (user) setForm({ display_name: user.display_name, timezone: user.timezone, base_currency: user.base_currency, cost_method: user.cost_method });
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
        <Select label="Moeda-base" description="Moeda em que patrimônio e resultados são consolidados." data={["USDT", "USDC", "BRL", "USD", "EUR", "BTC"]} value={form.base_currency} onChange={(v) => v && setForm({ ...form, base_currency: v })} />
        <Select
          label="Método de apuração de custo"
          data={[
            { value: "FIFO", label: "FIFO — primeiro a entrar, primeiro a sair" },
            { value: "AVERAGE", label: "Custo médio ponderado" },
          ]}
          value={form.cost_method}
          onChange={(v) => v && setForm({ ...form, cost_method: v })}
        />
        <Group justify="flex-end">
          <Button onClick={() => save.mutate()} loading={save.isPending}>Salvar</Button>
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
      <Sessions />
    </>
  );
}
