import { Alert, Badge, Card, Center, Group, Loader, Stack, Text, ThemeIcon, Title, Tooltip } from "@mantine/core";
import { IconAlertTriangle, IconInbox, IconInfoCircle } from "@tabler/icons-react";
import type { ReactNode } from "react";
import type { ConnectionStatus, Dec } from "../api/types";
import { fmtMoney, signColor } from "../lib/format";

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <Group justify="space-between" align="flex-start" mb="md" wrap="wrap">
      <div>
        <Title order={2}>{title}</Title>
        {description && (
          <Text c="dimmed" size="sm" maw={720}>
            {description}
          </Text>
        )}
      </div>
      {actions}
    </Group>
  );
}

export function StatCard({ label, value, hint, color, incomplete }: { label: string; value: ReactNode; hint?: ReactNode; color?: string; incomplete?: string }) {
  return (
    <Card withBorder radius="md" padding="md">
      <Group justify="space-between" gap={4} wrap="nowrap">
        <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
          {label}
        </Text>
        {incomplete && (
          <Tooltip label={incomplete} multiline w={260}>
            <Badge size="xs" color="yellow" variant="light" leftSection={<IconAlertTriangle size={10} />}>
              incompleto
            </Badge>
          </Tooltip>
        )}
      </Group>
      <Text fw={700} size="xl" c={color} mt={4} style={{ fontVariantNumeric: "tabular-nums" }}>
        {value}
      </Text>
      {hint && (
        <Text size="xs" c="dimmed" mt={2}>
          {hint}
        </Text>
      )}
    </Card>
  );
}

export function Money({ value, currency, colored }: { value: Dec | undefined; currency: string; colored?: boolean }) {
  if (value === null || value === undefined)
    return (
      <Tooltip label="Não calculado: dados insuficientes (cotação ou histórico ausente).">
        <Text span c="dimmed">
          não calculado
        </Text>
      </Tooltip>
    );
  return (
    <Text span c={colored ? signColor(value) : undefined} style={{ fontVariantNumeric: "tabular-nums" }} inherit>
      {fmtMoney(value, currency)}
    </Text>
  );
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <Center py="xl">
      <Stack align="center" gap="xs" maw={420}>
        <ThemeIcon size={48} radius="xl" variant="light" color="gray">
          <IconInbox />
        </ThemeIcon>
        <Text fw={600}>{title}</Text>
        <Text c="dimmed" size="sm" ta="center">
          {description}
        </Text>
        {action}
      </Stack>
    </Center>
  );
}

export function Loading() {
  return (
    <Center py="xl">
      <Loader />
    </Center>
  );
}

export function ErrorAlert({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <Alert color="red" icon={<IconAlertTriangle />} title="Não foi possível carregar" mb="md">
      {error instanceof Error ? error.message : String(error)}
    </Alert>
  );
}

export function InfoNote({ children }: { children: ReactNode }) {
  return (
    <Alert color="blue" variant="light" icon={<IconInfoCircle />} mb="md">
      {children}
    </Alert>
  );
}

const STATUS: Record<ConnectionStatus | string, { label: string; color: string }> = {
  pending_validation: { label: "Pendente de validação", color: "gray" },
  active: { label: "Ativa", color: "teal" },
  syncing: { label: "Sincronizando", color: "blue" },
  error: { label: "Com erro", color: "orange" },
  invalid_credentials: { label: "Credencial inválida", color: "red" },
  suspended: { label: "Suspensa", color: "gray" },
  pending_verification: { label: "Aguardando verificação", color: "yellow" },
  queued: { label: "Na fila", color: "gray" },
  running: { label: "Em execução", color: "blue" },
  succeeded: { label: "Concluída", color: "teal" },
  failed: { label: "Falhou", color: "red" },
  cancelled: { label: "Cancelada", color: "gray" },
  sent: { label: "Enviada", color: "teal" },
  pending: { label: "Pendente", color: "gray" },
  skipped: { label: "Ignorada", color: "gray" },
  complete: { label: "Completo", color: "teal" },
  incomplete: { label: "Incompleto", color: "yellow" },
};

export function StatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, color: "gray" };
  return (
    <Badge color={s.color} variant="light">
      {s.label}
    </Badge>
  );
}

export function SideBadge({ side }: { side: string }) {
  return (
    <Badge color={side === "BUY" ? "teal" : "red"} variant="light">
      {side === "BUY" ? "Compra" : "Venda"}
    </Badge>
  );
}
