import { Button, Checkbox, Divider, Group, Popover, ScrollArea, Stack, Text } from "@mantine/core";
import { IconColumns } from "@tabler/icons-react";

export interface ColumnOption {
  key: string;
  label: string;
}

/** Escolha das colunas visíveis de uma tabela. Ao menos uma coluna fica sempre marcada.
 * ``visible`` está na ordem de exibição (definida arrastando os cabeçalhos); ao marcar uma coluna
 * ela entra na posição original dela, sem desfazer a ordem escolhida. */
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
    let next: string[];
    if (!on) next = visible.filter((k) => k !== key);
    else {
      const all = columns.map((c) => c.key);
      const after = visible.findIndex((k) => all.indexOf(k) > all.indexOf(key));
      next = after < 0 ? [...visible, key] : [...visible.slice(0, after), key, ...visible.slice(after)];
    }
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
