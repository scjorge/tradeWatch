import { Badge, Card, Code, Group, SimpleGrid, Switch, Table, Tabs, Text, TextInput } from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, qs } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { InfoNote, Loading, PageHeader, StatCard } from "../components/common";
import { fmtDate } from "../lib/format";

interface AdminUser {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  email_verified: boolean;
  roles: string[];
  created_at: string;
  last_login_at: string | null;
  connections: number;
}

interface Mod {
  key: string;
  name: string;
  description: string;
  version: string;
  enabled: boolean;
  core: boolean;
}

function Users() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [q] = useDebouncedValue(search, 300);
  const users = useQuery({ queryKey: ["admin-users", q], queryFn: () => api<{ total: number; items: AdminUser[] }>(`/api/admin/users${qs({ q })}`) });
  const patch = (id: string, body: object) =>
    api(`/api/admin/users/${id}`, { method: "PATCH", body })
      .then(() => qc.invalidateQueries({ queryKey: ["admin-users"] }))
      .catch((e: Error) => notifications.show({ color: "red", message: e.message }));
  return (
    <>
      <TextInput placeholder="Buscar por e-mail" value={search} onChange={(e) => setSearch(e.currentTarget.value)} mb="sm" w={280} />
      {users.isLoading ? <Loading /> : (
        <Table.ScrollContainer minWidth={800}>
          <Table fz="sm" striped>
            <Table.Thead><Table.Tr><Table.Th>E-mail</Table.Th><Table.Th>Papéis</Table.Th><Table.Th>Conexões</Table.Th><Table.Th>Último login</Table.Th><Table.Th>Admin</Table.Th><Table.Th>Ativo</Table.Th></Table.Tr></Table.Thead>
            <Table.Tbody>
              {users.data?.items.map((u) => (
                <Table.Tr key={u.id}>
                  <Table.Td>{u.email} {!u.email_verified && <Badge size="xs" color="yellow" variant="light">não verificado</Badge>}</Table.Td>
                  <Table.Td>{u.roles.join(", ")}</Table.Td>
                  <Table.Td>{u.connections}</Table.Td>
                  <Table.Td>{fmtDate(u.last_login_at, user?.timezone)}</Table.Td>
                  <Table.Td>
                    <Switch size="xs" checked={u.roles.includes("admin")} disabled={u.id === user?.id} onChange={(e) => patch(u.id, { roles: e.currentTarget.checked ? ["user", "admin"] : ["user"] })} aria-label="Administrador" />
                  </Table.Td>
                  <Table.Td>
                    <Switch size="xs" checked={u.is_active} disabled={u.id === user?.id} onChange={(e) => patch(u.id, { is_active: e.currentTarget.checked })} aria-label="Ativo" />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </>
  );
}

function Modules() {
  const qc = useQueryClient();
  const mods = useQuery({ queryKey: ["admin-modules"], queryFn: () => api<Mod[]>("/api/admin/modules") });
  return (
    <SimpleGrid cols={{ base: 1, md: 3 }}>
      {mods.data?.map((m) => (
        <Card key={m.key} withBorder>
          <Group justify="space-between">
            <Text fw={600}>{m.name}</Text>
            <Switch
              checked={m.enabled}
              disabled={m.core}
              onChange={(e) =>
                api(`/api/admin/modules/${m.key}`, { method: "PATCH", body: { enabled: e.currentTarget.checked } })
                  .then(() => { void qc.invalidateQueries({ queryKey: ["admin-modules"] }); void qc.invalidateQueries({ queryKey: ["modules"] }); })
                  .catch((err: Error) => notifications.show({ color: "red", message: err.message }))
              }
              aria-label={`Ativar ${m.name}`}
            />
          </Group>
          <Text size="xs" c="dimmed">{m.description}</Text>
          <Text size="xs" mt={4}>versão {m.version}{m.core && " · núcleo"}</Text>
        </Card>
      ))}
    </SimpleGrid>
  );
}

function Audit() {
  const { user } = useAuth();
  const [action, setAction] = useState("");
  const [a] = useDebouncedValue(action, 300);
  const q = useQuery({ queryKey: ["audit", a], queryFn: () => api<{ items: { id: string; action: string; user_id: string | null; ip: string | null; details: object; created_at: string; target_type: string | null }[] }>(`/api/admin/audit${qs({ action: a, page_size: 100 })}`) });
  return (
    <>
      <TextInput placeholder="Filtrar ação (ex.: auth.)" value={action} onChange={(e) => setAction(e.currentTarget.value)} mb="sm" w={280} />
      <Table.ScrollContainer minWidth={800}>
        <Table fz="xs" striped>
          <Table.Thead><Table.Tr><Table.Th>Data</Table.Th><Table.Th>Ação</Table.Th><Table.Th>Usuário</Table.Th><Table.Th>IP</Table.Th><Table.Th>Detalhes</Table.Th></Table.Tr></Table.Thead>
          <Table.Tbody>
            {q.data?.items.map((r) => (
              <Table.Tr key={r.id}>
                <Table.Td>{fmtDate(r.created_at, user?.timezone)}</Table.Td>
                <Table.Td>{r.action}</Table.Td>
                <Table.Td><Text size="xs" c="dimmed">{r.user_id?.slice(0, 8) ?? "—"}</Text></Table.Td>
                <Table.Td>{r.ip ?? "—"}</Table.Td>
                <Table.Td><Code>{JSON.stringify(r.details)}</Code></Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </>
  );
}

function Health() {
  const health = useQuery({ queryKey: ["health"], queryFn: () => fetch("/api/health/ready").then((r) => r.json()), refetchInterval: 15_000 });
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: () => api<Record<string, unknown>>("/api/admin/metrics"), refetchInterval: 30_000 });
  const c = health.data?.checks ?? {};
  const m = metrics.data as { sync_jobs_by_status?: Record<string, number>; sync_avg_duration_seconds?: number | null; connections_with_repeated_failures?: number; users?: number } | undefined;
  return (
    <SimpleGrid cols={{ base: 2, md: 4 }}>
      <StatCard label="API" value={c.api ?? "…"} />
      <StatCard label="Banco" value={c.database ?? "…"} color={c.database === "ok" ? "teal" : "red"} />
      <StatCard label="Worker" value={c.worker ?? "…"} color={c.worker === "ok" ? "teal" : "orange"} hint={c.worker_last_seen ? `visto ${fmtDate(c.worker_last_seen)}` : undefined} />
      <StatCard label="Usuários" value={m?.users ?? "…"} />
      <StatCard label="Sincronizações 24h" value={Object.entries(m?.sync_jobs_by_status ?? {}).map(([k, v]) => `${k}: ${v}`).join(" · ") || "—"} />
      <StatCard label="Duração média" value={m?.sync_avg_duration_seconds ? `${m.sync_avg_duration_seconds.toFixed(1)}s` : "—"} />
      <StatCard label="Conexões com falhas repetidas" value={m?.connections_with_repeated_failures ?? 0} color={(m?.connections_with_repeated_failures ?? 0) > 0 ? "orange" : undefined} />
    </SimpleGrid>
  );
}

export function AdminPage() {
  return (
    <>
      <PageHeader title="Administração" description="Gestão da plataforma. Administradores não têm acesso às credenciais nem aos dados financeiros dos usuários." />
      <InfoNote>Alterações aqui ficam registradas na auditoria.</InfoNote>
      <Card withBorder radius="md">
        <Tabs defaultValue="health" keepMounted={false}>
          <Tabs.List mb="md">
            <Tabs.Tab value="health">Saúde</Tabs.Tab>
            <Tabs.Tab value="users">Usuários</Tabs.Tab>
            <Tabs.Tab value="modules">Módulos</Tabs.Tab>
            <Tabs.Tab value="audit">Auditoria</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="health"><Health /></Tabs.Panel>
          <Tabs.Panel value="users"><Users /></Tabs.Panel>
          <Tabs.Panel value="modules"><Modules /></Tabs.Panel>
          <Tabs.Panel value="audit"><Audit /></Tabs.Panel>
        </Tabs>
      </Card>
    </>
  );
}
