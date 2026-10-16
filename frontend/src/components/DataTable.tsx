import { Group, Pagination, Select, Table, Text, UnstyledButton } from "@mantine/core";
import { IconChevronDown, IconChevronUp, IconSelector } from "@tabler/icons-react";
import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  label: string;
  render: (row: T) => ReactNode;
  sortable?: boolean;
  align?: "left" | "right";
}

interface Props<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  total: number;
  page: number;
  pageSize: number;
  onPage: (p: number) => void;
  onPageSize?: (n: number) => void;
  sort?: string;
  direction?: "asc" | "desc";
  onSort?: (key: string, dir: "asc" | "desc") => void;
  minWidth?: number;
}

/** Tabela paginada com ordenação por coluna no servidor. */
export function DataTable<T>({ columns, rows, rowKey, total, page, pageSize, onPage, onPageSize, sort, direction, onSort, minWidth = 900 }: Props<T>) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <>
      <Table.ScrollContainer minWidth={minWidth}>
        <Table striped highlightOnHover verticalSpacing="xs" fz="sm">
          <Table.Thead>
            <Table.Tr>
              {columns.map((c) => {
                const active = sort === c.key;
                const Icon = active ? (direction === "asc" ? IconChevronUp : IconChevronDown) : IconSelector;
                return (
                  <Table.Th key={c.key} ta={c.align} aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : undefined}>
                    {c.sortable && onSort ? (
                      <UnstyledButton onClick={() => onSort(c.key, active && direction === "desc" ? "asc" : "desc")}>
                        <Group gap={2} justify={c.align === "right" ? "flex-end" : "flex-start"} wrap="nowrap">
                          <Text fw={600} size="sm">
                            {c.label}
                          </Text>
                          <Icon size={14} />
                        </Group>
                      </UnstyledButton>
                    ) : (
                      c.label
                    )}
                  </Table.Th>
                );
              })}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((r) => (
              <Table.Tr key={rowKey(r)}>
                {columns.map((c) => (
                  <Table.Td key={c.key} ta={c.align} style={c.align === "right" ? { fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" } : undefined}>
                    {c.render(r)}
                  </Table.Td>
                ))}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Group justify="space-between" mt="sm">
        <Text size="sm" c="dimmed">
          {total.toLocaleString("pt-BR")} registro(s)
        </Text>
        <Group gap="xs">
          {onPageSize && (
            <Select size="xs" w={90} data={["25", "50", "100"]} value={String(pageSize)} onChange={(v) => v && onPageSize(Number(v))} aria-label="Itens por página" />
          )}
          <Pagination size="sm" total={pages} value={page} onChange={onPage} />
        </Group>
      </Group>
    </>
  );
}
