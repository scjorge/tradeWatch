import { BarChart, LineChart } from "@mantine/charts";
import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Group,
  MultiSelect,
  NumberInput,
  Paper,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { MonthPickerInput } from "@mantine/dates";
import { IconChevronLeft, IconChevronRight, IconFilterOff } from "@tabler/icons-react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMemo, useState, type ReactNode } from "react";
import { api, qs } from "../../api/client";
import type { CycleRow, CycleSummary, Paged } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { EmptyState, Loading, Money, StatCard } from "../../components/common";
import { ColumnPicker } from "../../components/ColumnPicker";
import { useCurrency } from "../../lib/currency";
import { fmtDate, fmtMoney, fmtNumber, fmtPct, signColor } from "../../lib/format";
import { useModuleSettings } from "../../lib/moduleSettings";
export const STATUS_OPTIONS: { value: string; label: string; color: string }[] = [
  { value: "buy_order", label: "Ordem Comprar", color: "yellow" },
  { value: "open", label: "Ativo", color: "blue" },
  { value: "sell_order", label: "Ordem Vender", color: "grape" },
  { value: "closed", label: "Concluído", color: "teal" },
];
const QUOTES = ["USDT", "BRL", "USDC", "FDUSD", "BTC", "ETH", "BNB"];

// ------------------------------------------------------------------ filtros específicos de resultado
export interface ResultFilters {
  status: string[];
  result: "" | "gain" | "loss" | "incomplete";
  quote: string | null;
  minPnl: number | string;
  maxPnl: number | string;
  minPct: number | string;
  maxPct: number | string;
  minDays: number | string;
  maxDays: number | string;
}

export const EMPTY_RESULT_FILTERS: ResultFilters = { status: [], result: "", quote: null, minPnl: "", maxPnl: "", minPct: "", maxPct: "", minDays: "", maxDays: "" };

export function resultParams(r: ResultFilters): Record<string, unknown> {
  return {
    status: r.status,
    result: r.result || undefined,
    quote: r.quote ?? undefined,
    min_pnl: r.minPnl,
    max_pnl: r.maxPnl,
    min_pct: r.minPct,
    max_pct: r.maxPct,
    min_days: r.minDays,
    max_days: r.maxDays,
  };
}

export function ResultFiltersBar({ value, onChange }: { value: ResultFilters; onChange: (v: ResultFilters) => void }) {
  const set = (p: Partial<ResultFilters>) => onChange({ ...value, ...p });
  return (
    <Paper withBorder p="sm" radius="md" mb="md">
      <Group gap="sm" align="flex-end" wrap="wrap">
        <SegmentedControl
          size="xs"
          value={value.result}
          onChange={(v) => set({ result: v as ResultFilters["result"] })}
          data={[
            { label: "Todas", value: "" },
            { label: "Com lucro", value: "gain" },
            { label: "Com prejuízo", value: "loss" },
            { label: "Incompletas", value: "incomplete" },
          ]}
          aria-label="Resultado"
        />
        <MultiSelect size="xs" label="Status" placeholder={value.status.length ? undefined : "Todos"} data={STATUS_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} value={value.status} onChange={(v) => set({ status: v })} clearable w={220} />
        <Select size="xs" label="Moeda" data={QUOTES} value={value.quote} onChange={(v) => set({ quote: v })} clearable w={95} />
        <Group gap={4} align="flex-end" wrap="nowrap">
          <NumberInput size="xs" label="Lucro (R$) de" value={value.minPnl} onChange={(v) => set({ minPnl: v })} w={100} decimalSeparator="," thousandSeparator="." />
          <NumberInput size="xs" label="até" value={value.maxPnl} onChange={(v) => set({ maxPnl: v })} w={90} decimalSeparator="," thousandSeparator="." />
        </Group>
        <Group gap={4} align="flex-end" wrap="nowrap">
          <NumberInput size="xs" label="% de" value={value.minPct} onChange={(v) => set({ minPct: v })} w={75} decimalSeparator="," />
          <NumberInput size="xs" label="até" value={value.maxPct} onChange={(v) => set({ maxPct: v })} w={75} decimalSeparator="," />
        </Group>
        <Group gap={4} align="flex-end" wrap="nowrap">
          <NumberInput size="xs" label="Dias de" min={0} value={value.minDays} onChange={(v) => set({ minDays: v })} w={75} />
          <NumberInput size="xs" label="até" min={0} value={value.maxDays} onChange={(v) => set({ maxDays: v })} w={75} />
        </Group>
        <Button size="xs" variant="subtle" leftSection={<IconFilterOff size={14} />} onClick={() => onChange(EMPTY_RESULT_FILTERS)}>
          Limpar
        </Button>
      </Group>
      <Text size="xs" c="dimmed" mt={6}>
        Filtros de lucro, % e dias consideram apenas operações concluídas. O período usa a data da venda (concluídas) ou da compra (em aberto).
      </Text>
    </Paper>
  );
}

// ------------------------------------------------------------------ indicadores
export function SummaryCards({ s }: { s: CycleSummary }) {
  const cur = useCurrency();
  return (
    <>
      <SimpleGrid cols={{ base: 2, md: 4 }} mb="sm">
        <StatCard
          label={`Lucro / prejuízo (${cur})`}
          value={<Money value={s.pnl_brl} currency={cur} colored />}
          color={signColor(s.pnl_brl)}
          hint={`Rentabilidade ${fmtPct(s.return_pct)} sobre ${fmtMoney(s.invested_closed_brl, cur)} · ganhos ${fmtMoney(s.gains_brl, cur)} · perdas ${fmtMoney(s.losses_brl, cur)}`}
          incomplete={s.incomplete_count ? `${s.incomplete_count} operação(ões) sem compra correspondente ou sem câmbio — fora da soma` : undefined}
        />
        <StatCard label="Operações concluídas" value={s.closed_count} hint={`${s.wins} com lucro · ${s.losses} com prejuízo · acerto ${fmtPct(s.win_rate_pct)}`} />
        <StatCard label="Ganho médio / perda média" value={s.avg_gain_brl ? <Money value={s.avg_gain_brl} currency={cur} colored /> : "—"} hint={`Perda média ${fmtMoney(s.avg_loss_brl, cur)} · payoff ${s.payoff_ratio !== null ? fmtNumber(s.payoff_ratio, 2) : "—"}`} />
        <StatCard
          label="Fator de lucro"
          value={s.profit_factor !== null ? fmtNumber(s.profit_factor, 2) : "—"}
          hint="Ganhos ÷ perdas. Acima de 1 = lucrativo"
          color={s.profit_factor !== null ? (s.profit_factor >= 1 ? "teal" : "red") : undefined}
        />
      </SimpleGrid>
      <SimpleGrid cols={{ base: 2, md: 4 }} mb="md">
        <StatCard
          label="Em aberto (Ativo)"
          value={<Money value={s.unrealized_brl} currency={cur} colored />}
          hint={`${s.open_count} posição(ões) · ${fmtMoney(s.open_invested_brl, cur)} investidos · ${s.pending_orders} ordem(ns)`}
          incomplete={s.unrealized_complete ? undefined : "Alguma posição sem cotação atual; clique em Cotações"}
        />
        <StatCard label="Melhor / pior operação" value={s.best ? <Money value={s.best.pnl_brl} currency={cur} colored /> : "—"} hint={s.worst ? `Pior: ${fmtMoney(s.worst.pnl_brl, cur)} (${s.worst.asset})` : "—"} />
        <StatCard label="Tempo médio por operação" value={s.avg_holding_days !== null ? `${fmtNumber(s.avg_holding_days, 1)} dia(s)` : "—"} />
        <StatCard label="Taxas · efeito câmbio" value={fmtMoney(s.fees_brl, cur)} hint={`Variação do câmbio entre compra e venda: ${fmtMoney(s.fx_effect_brl, cur)}`} />
      </SimpleGrid>
    </>
  );
}

// ------------------------------------------------------------------ tabela compra → venda
function statusBadge(c: CycleRow) {
  const s = STATUS_OPTIONS.find((o) => o.value === c.status)!;
  return <Badge color={s.color} variant="light">{s.label}</Badge>;
}

interface Col {
  key: string;
  label: string;
  sort?: string;
  right?: boolean;
  /** Valores da venda são estimados em posições abertas/ordens: exibidos em cinza. */
  estimable?: boolean;
  cell: (c: CycleRow, fmtD: (s: string | null) => string) => ReactNode;
}

function columnsFor(cur: string): Col[] {
  return [
  { key: "status", label: "Status", sort: "status", cell: (c) => <span style={{ display: "inline-block", minWidth: 110 }}>{statusBadge(c)}</span> },
  {
    key: "asset",
    label: "Criptomoeda",
    sort: "asset",
    cell: (c) => (
      <Text span size="xs" fw={600}>
        {c.asset}
        {!c.complete && (
          <Tooltip label={c.note ?? "Incompleta"} multiline w={280}>
            <Badge ml={4} size="xs" color="yellow" variant="light">incompleta</Badge>
          </Tooltip>
        )}
      </Text>
    ),
  },
  { key: "quote", label: "Moeda", cell: (c) => `${c.quote ?? "—"}${c.sell_quote && c.sell_quote !== c.quote ? ` → ${c.sell_quote}` : ""}` },
  { key: "account", label: "Conta", cell: (c) => <Text size="xs" truncate maw={130}>{c.account ?? "—"}</Text> },
  { key: "buy_at", label: "Data Compra", sort: "buy_at", cell: (c, d) => d(c.buy_at) },
  { key: "buy_quantity", label: "Quant. a Comprar", right: true, cell: (c) => fmtNumber(c.buy_quantity) },
  { key: "buy_price", label: "Valor Unit. Compra", right: true, cell: (c) => fmtNumber(c.buy_price) },
  { key: "buy_fee", label: "Taxa", right: true, cell: (c) => (c.buy_fee && Number(c.buy_fee) ? `${fmtNumber(c.buy_fee)} ${c.buy_fee_asset ?? ""}` : "—") },
  {
    key: "fees_brl",
    label: `Taxa ${cur}`,
    right: true,
    cell: (c) => (
      <Tooltip label={c.status === "closed" ? `Taxas da compra e da venda convertidas para ${cur}` : `Taxa da compra convertida para ${cur}`} disabled={!c.fees_brl}>
        <span>{c.fees_brl !== null && Number(c.fees_brl) ? fmtMoney(c.fees_brl, cur) : "—"}</span>
      </Tooltip>
    ),
  },
  { key: "buy_fx", label: "Câmbio Compra", right: true, cell: (c) => fmtNumber(c.buy_fx) },
  { key: "buy_unit_brl", label: `Unit. Compra ${cur}`, right: true, cell: (c) => fmtNumber(c.buy_unit_brl) },
  { key: "buy_total", label: "Total da Compra", right: true, cell: (c) => fmtNumber(c.buy_total) },
  { key: "buy_total_brl", label: `Compra ${cur}`, sort: "buy_total_brl", right: true, cell: (c) => fmtMoney(c.buy_total_brl, cur) },
  { key: "sell_at", label: "Data Venda", sort: "sell_at", cell: (c, d) => d(c.sell_at) },
  { key: "sell_quantity", label: "Quant. a Vender", right: true, cell: (c) => (c.status === "buy_order" ? "—" : fmtNumber(c.sell_quantity)) },
  { key: "sell_price", label: "Valor Unit. Venda", right: true, estimable: true, cell: (c) => fmtNumber(c.sell_price) },
  { key: "sell_fee", label: "Taxa Venda", right: true, cell: (c) => (c.sell_fee && Number(c.sell_fee) ? `${fmtNumber(c.sell_fee)} ${c.sell_fee_asset ?? ""}` : "—") },
  { key: "sell_fx", label: "Câmbio Venda", right: true, estimable: true, cell: (c) => fmtNumber(c.sell_fx) },
  { key: "sell_unit_brl", label: `Unit. Venda ${cur}`, right: true, estimable: true, cell: (c) => fmtNumber(c.sell_unit_brl) },
  { key: "sell_total", label: "Total a Venda", right: true, estimable: true, cell: (c) => fmtNumber(c.sell_total) },
  { key: "sell_total_brl", label: `Venda ${cur}`, right: true, estimable: true, cell: (c) => fmtMoney(c.sell_total_brl, cur) },
  {
    key: "pnl_brl",
    label: "Lucro / Prejuízo",
    sort: "pnl_brl",
    right: true,
    cell: (c) =>
      c.pnl_brl === null ? (
        <Text span size="xs" c="dimmed">{c.status === "buy_order" ? "—" : c.estimated ? "sem cotação" : "não calculado"}</Text>
      ) : (
        <Tooltip
          label={c.status === "open" ? `Não realizado pela cotação atual (${c.price_source ?? "—"})` : "Previsto pelo preço-alvo da ordem de venda"}
          disabled={!c.estimated}
        >
          <Text span size="xs" fw={600} c={signColor(c.pnl_brl)} fs={c.estimated ? "italic" : undefined}>
            {fmtMoney(c.pnl_brl, cur)}
            {c.estimated && "*"}
          </Text>
        </Tooltip>
      ),
  },
  { key: "pnl_pct", label: "%", sort: "pnl_pct", right: true, cell: (c) => <Text span size="xs" c={signColor(c.pnl_pct ?? undefined)}>{fmtPct(c.pnl_pct)}</Text> },
  { key: "pnl_quote", label: "Lucro na moeda", right: true, cell: (c) => <Text span size="xs" c={signColor(c.pnl_quote)}>{c.pnl_quote ? `${fmtNumber(c.pnl_quote)} ${c.quote ?? ""}` : "—"}</Text> },
  { key: "fx_effect_brl", label: "Efeito câmbio", right: true, cell: (c) => <Text span size="xs" c={signColor(c.fx_effect_brl)}>{fmtMoney(c.fx_effect_brl, cur)}</Text> },
  { key: "holding_days", label: "Dias", sort: "holding_days", right: true, cell: (c) => (c.holding_days !== null ? fmtNumber(c.holding_days, 1) : "—") },
];
}
const COLUMNS = columnsFor("BRL"); // apenas para as chaves; os rótulos usam a moeda do usuário

const OPTIONAL = new Set(["buy_fx", "sell_fee", "sell_fx", "pnl_quote", "fx_effect_brl"]);
export const DEFAULT_COLUMNS = COLUMNS.filter((c) => !OPTIONAL.has(c.key)).map((c) => c.key);
const PREF_KEY = "buysell_columns";

// Versão consolidada: execuções da mesma ordem somadas numa linha, com a contagem de execuções.
const EXECUTIONS_COL: Col = {
  key: "executions",
  label: "Execuções",
  right: true,
  cell: (c) => (
    <Tooltip label={`${c.buy_executions ?? 0} execução(ões) de compra · ${c.sell_executions ?? 0} de venda`}>
      <span>{c.status === "closed" ? `${c.buy_executions ?? 0} C · ${c.sell_executions ?? 0} V` : `${c.buy_executions || c.sell_executions || 1}`}</span>
    </Tooltip>
  ),
};
const withExecutions = (cols: Col[]): Col[] => [...cols.slice(0, 4), EXECUTIONS_COL, ...cols.slice(4)];
const CONSOLIDATED_DEFAULT_COLUMNS = withExecutions(COLUMNS).filter((c) => !OPTIONAL.has(c.key)).map((c) => c.key);
const CONSOLIDATED_PREF_KEY = "buysell_consolidated_columns";

export function CyclesTable({ params, consolidated = false }: { params: Record<string, unknown>; consolidated?: boolean }) {
  const { user } = useAuth();
  const prefs = useModuleSettings("trades");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [sort, setSort] = useState({ key: "ref_at", dir: "desc" as "asc" | "desc" });
  const endpoint = consolidated ? "/api/trades/cycles/consolidated" : "/api/trades/cycles";
  const cur = useCurrency();
  const columns = useMemo(() => (consolidated ? withExecutions(columnsFor(cur)) : columnsFor(cur)), [consolidated, cur]);
  const defaults = consolidated ? CONSOLIDATED_DEFAULT_COLUMNS : DEFAULT_COLUMNS;
  const prefKey = consolidated ? CONSOLIDATED_PREF_KEY : PREF_KEY;
  const q = useQuery({
    queryKey: [consolidated ? "cycles-consolidated" : "cycles", params, page, pageSize, sort],
    queryFn: () => api<Paged<CycleRow>>(`${endpoint}${qs({ ...params, page, page_size: pageSize, sort: sort.key, direction: sort.dir })}`),
    placeholderData: keepPreviousData,
  });
  const tz = user?.timezone;
  const d = (s: string | null) => (s ? fmtDate(s, tz, false) : "—");

  const saved = prefs.settings?.[prefKey];
  const known = new Set(columns.map((c) => c.key));
  const visibleKeys = Array.isArray(saved) ? (saved as string[]).filter((k) => known.has(k)) : defaults;
  const visible = columns.filter((c) => visibleKeys.includes(c.key));

  if (q.isLoading || !prefs.loaded) return <Loading />;
  if (!q.data?.total)
    return <EmptyState title="Nenhuma operação encontrada" description="Ajuste os filtros ou sincronize uma integração para ver suas compras e vendas." />;

  const pages = Math.max(1, Math.ceil(q.data.total / pageSize));
  return (
    <>
      <Group justify="flex-end" mb="xs">
        <ColumnPicker
          columns={columns.map((c) => ({ key: c.key, label: c.label }))}
          visible={visibleKeys}
          defaults={defaults}
          onChange={(keys) => prefs.save({ [prefKey]: keys })}
        />
      </Group>
      <Table.ScrollContainer minWidth={Math.max(700, visible.length * 95)}>
        <Table striped highlightOnHover fz="xs" verticalSpacing={6}>
          <Table.Thead>
            <Table.Tr>
              {visible.map((col) => (
                <Table.Th key={col.key} ta={col.right ? "right" : undefined} style={{ whiteSpace: "nowrap" }}>
                  {col.sort ? (
                    <UnstyledButton onClick={() => setSort((s) => ({ key: col.sort!, dir: s.key === col.sort && s.dir === "desc" ? "asc" : "desc" }))}>
                      <Text fw={600} size="xs">
                        {col.label}
                        {sort.key === col.sort ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}
                      </Text>
                    </UnstyledButton>
                  ) : (
                    <Text fw={600} size="xs">{col.label}</Text>
                  )}
                </Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {q.data.items.map((c) => (
              <Table.Tr key={c.id}>
                {visible.map((col) => (
                  <Table.Td key={col.key} ta={col.right ? "right" : undefined} c={col.estimable && c.estimated ? "dimmed" : undefined} style={col.right ? { whiteSpace: "nowrap" } : undefined}>
                    {col.cell(c, d)}
                  </Table.Td>
                ))}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Group justify="space-between" mt="sm">
        <Text size="xs" c="dimmed">
          {q.data.total.toLocaleString("pt-BR")} linha(s)
          {consolidated && " · execuções da mesma ordem somadas; valores unitários e câmbio são médias ponderadas"} · * estimado (posição aberta pela cotação atual ou ordem de venda pelo preço-alvo); só "Concluído" entra no lucro realizado.
        </Text>
        <Group gap="xs">
          <Select size="xs" w={90} data={["25", "50", "100", "200"]} value={String(pageSize)} onChange={(v) => { if (v) { setPageSize(Number(v)); setPage(1); } }} aria-label="Linhas por página" />
          <Button.Group>
            <Button size="xs" variant="default" disabled={page <= 1} onClick={() => setPage(page - 1)}>Anterior</Button>
            <Button size="xs" variant="default" disabled>{page}/{pages}</Button>
            <Button size="xs" variant="default" disabled={page >= pages} onClick={() => setPage(page + 1)}>Próxima</Button>
          </Button.Group>
        </Group>
      </Group>
    </>
  );
}

// ------------------------------------------------------------------ análises
export function PeriodsPanel({ params }: { params: Record<string, unknown> }) {
  const cur = useCurrency();
  const [granularity, setGranularity] = useState("month");
  const q = useQuery({
    queryKey: ["cycles-summary", params, granularity],
    queryFn: () => api<CycleSummary>(`/api/trades/cycles/summary${qs({ ...params, granularity })}`),
    placeholderData: keepPreviousData,
  });
  const periods = q.data?.periods ?? [];
  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm" c="dimmed">Operações concluídas agrupadas pela data da venda, com ganhos, perdas e acumulado.</Text>
        <SegmentedControl size="xs" value={granularity} onChange={setGranularity} data={[{ label: "Dia", value: "day" }, { label: "Semana", value: "week" }, { label: "Mês", value: "month" }, { label: "Ano", value: "year" }]} />
      </Group>
      {!periods.length ? (
        <EmptyState title="Sem operações concluídas no período" description="Ajuste os filtros para ver o resultado por período." />
      ) : (
        <>
          <SimpleGrid cols={{ base: 1, lg: 2 }}>
            <Card withBorder>
              <Text fw={600} size="sm" mb="xs">Ganhos e perdas por período</Text>
              <BarChart
                h={240}
                type="stacked"
                data={periods.map((p) => ({ period: p.period, Ganhos: Number(p.gains_brl), Perdas: Number(p.losses_brl) }))}
                dataKey="period"
                series={[{ name: "Ganhos", color: "teal.6" }, { name: "Perdas", color: "red.6" }]}
                valueFormatter={(v) => fmtMoney(v, cur)}
              />
            </Card>
            <Card withBorder>
              <Text fw={600} size="sm" mb="xs">Resultado acumulado</Text>
              <LineChart h={240} data={periods.map((p) => ({ period: p.period, Acumulado: Number(p.cumulative_brl) }))} dataKey="period" series={[{ name: "Acumulado", color: "blue.6" }]} curveType="monotone" valueFormatter={(v) => fmtMoney(v, cur)} />
            </Card>
          </SimpleGrid>
          <Table.ScrollContainer minWidth={820}>
            <Table striped fz="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Período</Table.Th>
                  <Table.Th ta="right">Operações</Table.Th>
                  <Table.Th ta="right">Acerto</Table.Th>
                  <Table.Th ta="right">Ganhos</Table.Th>
                  <Table.Th ta="right">Perdas</Table.Th>
                  <Table.Th ta="right">Resultado</Table.Th>
                  <Table.Th ta="right">Rentab.</Table.Th>
                  <Table.Th ta="right">vs. anterior</Table.Th>
                  <Table.Th ta="right">Taxas</Table.Th>
                  <Table.Th ta="right">Acumulado</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {periods.map((p) => (
                  <Table.Tr key={p.period}>
                    <Table.Td>{p.period}</Table.Td>
                    <Table.Td ta="right">{p.count}</Table.Td>
                    <Table.Td ta="right">{fmtPct(p.win_rate_pct)}</Table.Td>
                    <Table.Td ta="right" c="teal">{fmtMoney(p.gains_brl, cur)}</Table.Td>
                    <Table.Td ta="right" c="red">{fmtMoney(p.losses_brl, cur)}</Table.Td>
                    <Table.Td ta="right"><Money value={p.pnl_brl} currency={cur} colored /></Table.Td>
                    <Table.Td ta="right" c={signColor(p.return_pct ?? undefined)}>{fmtPct(p.return_pct)}</Table.Td>
                    <Table.Td ta="right" c={signColor(p.change_vs_prev_brl)}>{p.change_vs_prev_brl ? fmtMoney(p.change_vs_prev_brl, cur) : "—"}</Table.Td>
                    <Table.Td ta="right">{fmtMoney(p.fees_brl, cur)}</Table.Td>
                    <Table.Td ta="right"><Money value={p.cumulative_brl} currency={cur} colored /></Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </>
      )}
    </Stack>
  );
}

export function CalendarPanel({ params }: { params: Record<string, unknown> }) {
  const cur = useCurrency();
  const [month, setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  const key = `${month.getFullYear()}-${String(month.getMonth() + 1).padStart(2, "0")}`;
  const { start: _s, end: _e, ...rest } = params;
  const q = useQuery({
    queryKey: ["cycles-calendar", key, rest],
    queryFn: () => api<{ days: { date: string; pnl_brl: string; count: number }[]; total_brl: string }>(`/api/trades/cycles/calendar${qs({ ...rest, month: key })}`),
  });
  const shift = (n: number) => setMonth(new Date(month.getFullYear(), month.getMonth() + n, 1));
  const max = Math.max(1, ...(q.data?.days ?? []).map((d) => Math.abs(Number(d.pnl_brl))));
  return (
    <Stack>
      <Group justify="space-between">
        <Group gap="xs">
          <ActionIcon variant="default" onClick={() => shift(-1)} aria-label="Mês anterior"><IconChevronLeft size={16} /></ActionIcon>
          <MonthPickerInput value={month} onChange={(d) => d && setMonth(d)} valueFormat="MMMM [de] YYYY" w={190} size="sm" />
          <ActionIcon variant="default" onClick={() => shift(1)} aria-label="Próximo mês"><IconChevronRight size={16} /></ActionIcon>
        </Group>
        <Text size="sm">Total do mês: <Money value={q.data?.total_brl ?? null} currency={cur} colored /></Text>
      </Group>
      {q.isLoading ? (
        <Loading />
      ) : (
        <SimpleGrid cols={7} spacing={6}>
          {["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"].map((w) => <Text key={w} size="xs" c="dimmed" ta="center" fw={600}>{w}</Text>)}
          {Array.from({ length: month.getDay() }).map((_, i) => <div key={`e${i}`} />)}
          {q.data?.days.map((d) => {
            const v = Number(d.pnl_brl);
            const alpha = d.count ? 0.15 + 0.6 * (Math.abs(v) / max) : 0;
            const bg = v > 0 ? `rgba(18,184,134,${alpha})` : v < 0 ? `rgba(250,82,82,${alpha})` : undefined;
            return (
              <Paper key={d.date} withBorder p={6} radius="sm" style={{ background: bg, minHeight: 58 }}>
                <Text size="xs" c="dimmed">{Number(d.date.slice(8))}</Text>
                {d.count > 0 && (
                  <>
                    <Text size="xs" fw={700} c={signColor(v)}>{fmtMoney(d.pnl_brl, cur).replace(` ${cur}`, "")}</Text>
                    <Text size="10px" c="dimmed">{d.count} op.</Text>
                  </>
                )}
              </Paper>
            );
          })}
        </SimpleGrid>
      )}
      <Text size="xs" c="dimmed">Soma do lucro/prejuízo das vendas de cada dia (os demais filtros continuam valendo).</Text>
    </Stack>
  );
}

export function AssetsPanel({ s }: { s?: CycleSummary }) {
  const cur = useCurrency();
  if (!s?.by_asset.length) return <EmptyState title="Sem operações concluídas" description="O ranking por ativo aparece após as primeiras vendas." />;
  return (
    <Table striped fz="sm">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Ativo</Table.Th>
          <Table.Th ta="right">Operações</Table.Th>
          <Table.Th ta="right">Acerto</Table.Th>
          <Table.Th ta="right">Rentab.</Table.Th>
          <Table.Th ta="right">Resultado</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {s.by_asset.map((a) => (
          <Table.Tr key={a.asset}>
            <Table.Td fw={600}>{a.asset}</Table.Td>
            <Table.Td ta="right">{a.count}</Table.Td>
            <Table.Td ta="right">{fmtPct(a.win_rate_pct)}</Table.Td>
            <Table.Td ta="right" c={signColor(a.return_pct ?? undefined)}>{fmtPct(a.return_pct)}</Table.Td>
            <Table.Td ta="right"><Money value={a.pnl_brl} currency={cur} colored /></Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
