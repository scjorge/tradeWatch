import { Button, Checkbox, Divider, Group, Popover, ScrollArea, Stack, Text } from "@mantine/core";
import { IconColumns } from "@tabler/icons-react";

export interface ColumnOption {
  key: string;
  label: string;
}

/** Escolha das colunas visíveis de uma tabela. Ao menos uma coluna fica sempre marcada. */
export function ColumnPicker({
  columns,
  visible,
  defaults,
  onChange,
}: {
  columns: ColumnOption[];
  visible: string[];
  defaults: string[];
  onChange: (keys: string[]) => void;
}) {
  const set = new Set(visible);
  const toggle = (key: string, on: boolean) => {
    const next = columns.map((c) => c.key).filter((k) => (k === key ? on : set.has(k)));
    if (next.length) onChange(next);
  };
  return (
    <Popover position="bottom-end" shadow="md" width={260} withinPortal>
      <Popover.Target>
        <Button size="xs" variant="default" leftSection={<IconColumns size={14} />}>
          Colunas ({visible.length}/{columns.length})
        </Button>
      </Popover.Target>
      <Popover.Dropdown>
        <Text size="xs" c="dimmed" mb={6}>
          Salvo no seu perfil e aplicado em qualquer dispositivo.
        </Text>
        <ScrollArea.Autosize mah={360}>
          <Stack gap={6}>
            {columns.map((c) => (
              <Checkbox
                key={c.key}
                size="xs"
                label={c.label}
                checked={set.has(c.key)}
                disabled={set.has(c.key) && visible.length === 1}
                onChange={(e) => toggle(c.key, e.currentTarget.checked)}
              />
            ))}
          </Stack>
        </ScrollArea.Autosize>
        <Divider my="xs" />
        <Group justify="space-between">
          <Button size="compact-xs" variant="subtle" onClick={() => onChange(columns.map((c) => c.key))}>
            Mostrar todas
          </Button>
          <Button size="compact-xs" variant="subtle" onClick={() => onChange(defaults)}>
            Restaurar padrão
          </Button>
        </Group>
      </Popover.Dropdown>
    </Popover>
  );
}
