import { Button, Group, MultiSelect, Paper, SegmentedControl, Select, TextInput } from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { IconFilterOff } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Connection } from "../api/types";
import { useFilters, type Period } from "./FiltersContext";

/** Filtros globais: período, corretora, conta, ativo, mercado e tipo de operação. */
export function FiltersBar({ showSide = true }: { showSide?: boolean }) {
  const { filters, setFilters, reset } = useFilters();
  const conns = useQuery({ queryKey: ["connections"], queryFn: () => api<Connection[]>("/api/integrations/connections") });
  const providers = [...new Set((conns.data ?? []).map((c) => c.provider))];

  return (
    <Paper withBorder p="sm" radius="md" mb="md">
      <Group gap="sm" align="flex-end" wrap="wrap">
        <SegmentedControl
          size="xs"
          value={filters.period}
          onChange={(v) => setFilters({ period: v as Period })}
          data={[
            { label: "Este mês", value: "month" },
            { label: "Mês anterior", value: "prevmonth" },
            { label: "30d", value: "30d" },
            { label: "90d", value: "90d" },
            { label: "Este ano", value: "ytd" },
            { label: "12 meses", value: "1y" },
            { label: "Tudo", value: "all" },
            { label: "Período", value: "custom" },
          ]}
          aria-label="Período"
        />
        {filters.period === "custom" && (
          <DatePickerInput
            type="range"
            size="xs"
            label="Intervalo"
            placeholder="Escolha as datas"
            value={filters.range}
            onChange={(r) => setFilters({ range: r })}
            valueFormat="DD/MM/YYYY"
            w={230}
          />
        )}
        {providers.length > 1 && (
          <Select size="xs" label="Corretora" clearable data={providers} value={filters.provider || null} onChange={(v) => setFilters({ provider: v ?? "" })} w={130} />
        )}
        <MultiSelect
          size="xs"
          label="Conta"
          placeholder={filters.connectionIds.length ? undefined : "Todas"}
          data={(conns.data ?? []).map((c) => ({ value: c.id, label: c.name }))}
          value={filters.connectionIds}
          onChange={(v) => setFilters({ connectionIds: v })}
          clearable
          w={220}
        />
        <TextInput
          size="xs"
          label="Ativo"
          placeholder="ex.: BTC"
          value={filters.asset}
          onChange={(e) => setFilters({ asset: e.currentTarget.value.toUpperCase().trim() })}
          w={100}
        />
        <Select size="xs" label="Mercado" data={[{ value: "spot", label: "Spot" }]} clearable value={filters.market || null} onChange={(v) => setFilters({ market: v ?? "" })} w={100} />
        {showSide && (
          <Select
            size="xs"
            label="Tipo"
            clearable
            data={[
              { value: "BUY", label: "Compra" },
              { value: "SELL", label: "Venda" },
            ]}
            value={filters.side || null}
            onChange={(v) => setFilters({ side: (v ?? "") as "" | "BUY" | "SELL" })}
            w={110}
          />
        )}
        <Button size="xs" variant="subtle" leftSection={<IconFilterOff size={14} />} onClick={reset}>
          Limpar
        </Button>
      </Group>
    </Paper>
  );
}
