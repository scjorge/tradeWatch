import { Badge, Button, Card, Group, Menu, NumberInput, Tabs, Text, TextInput, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useDebouncedValue } from "@mantine/hooks";
import { IconDownload, IconRefresh, IconSearch } from "@tabler/icons-react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, qs } from "../api/client";
import type { CycleSummary, Execution, Paged } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { DataTable, type Column } from "../components/DataTable";
import { SyncButton } from "../components/SyncButton";
import { useFilterParams } from "../components/FiltersContext";
import { FiltersBar } from "../components/FiltersBar";
import { EmptyState, ErrorAlert, InfoNote, Loading, PageHeader, SideBadge, StatusBadge } from "../components/common";
import { fmtDate, fmtMoney, fmtNumber } from "../lib/format";
import { AssetsPanel, CalendarPanel, CyclesTable, EMPTY_RESULT_FILTERS, PeriodsPanel, ResultFiltersBar, SummaryCards, resultParams, type ResultFilters } from "./operations/BuySell";

interface Order {
  id: string;
  external_id: string;
  symbol: string;
  side: string;
  type: string;
  status: string;
  price: string | null;
  orig_qty: string;
  executed_qty: string;
  cumulative_quote_qty: string;
  placed_at: string;
  executions: number;
}

interface Movement {
  id: string;
  kind: string;
  asset: string;
  amount: string;
  fee: string;
  network: string | null;
  tx_id: string | null;
  status: string;
  occurred_at: string;
}

function ExecutionsTab() {
  const { user } = useAuth();
  const params = useFilterParams();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [sort, setSort] = useState("executed_at");
  const [direction, setDirection] = useState<"asc" | "desc">("desc");
  const [search, setSearch] = useState("");
  const [minV, setMinV] = useState<number | string>("");
  const [maxV, setMaxV] = useState<number | string>("");
  const [q] = useDebouncedValue(search, 300);
  const all = { ...params, q, min_value: minV, max_value: maxV, sort, direction };
  const query = useQuery({
    queryKey: ["executions", all, page, pageSize],
    queryFn: () => api<Paged<Execution>>(`/api/trades/executions${qs({ ...all, page, page_size: pageSize })}`),
    placeholderData: keepPreviousData,
  });
  const tz = user?.timezone;

  const cols: Column<Execution>[] = [
    { key: "executed_at", label: "Data e hora", sortable: true, render: (e) => fmtDate(e.executed_at, tz) },
    { key: "connection", label: "Corretora / conta", render: (e) => <Text size="sm">{e.provider} · {e.connection_name}</Text> },
    { key: "market", label: "Mercado", render: (e) => e.market },
    { key: "symbol", label: "Par", sortable: true, render: (e) => <Badge variant="outline">{e.symbol}</Badge> },
    { key: "side", label: "Lado", sortable: true, render: (e) => <SideBadge side={e.side} /> },
    { key: "quantity", label: "Quantidade", sortable: true, align: "right", render: (e) => `${fmtNumber(e.quantity)} ${e.base_asset}` },
    { key: "price", label: "Preço unitário", sortable: true, align: "right", render: (e) => fmtMoney(e.price, e.quote_asset) },
    { key: "quote_quantity", label: "Valor bruto", sortable: true, align: "right", render: (e) => fmtMoney(e.gross_value, e.quote_asset) },
    {
      key: "fee",
      label: "Taxa",
      sortable: true,
      align: "right",
      render: (e) => (
        <Tooltip label={e.fee_value ? `≈ ${fmtMoney(e.fee_value, e.fee_value_currency ?? "")}` : "Sem cotação da taxa"} disabled={!Number(e.fee)}>
          <span>{Number(e.fee) ? `${fmtNumber(e.fee)} ${e.fee_asset ?? ""}` : "—"}</span>
        </Tooltip>
      ),
    },
    { key: "net", label: "Valor líquido", align: "right", render: (e) => fmtMoney(e.net_value, e.quote_asset) },
    { key: "external_id", label: "ID externo", render: (e) => <Text size="xs" c="dimmed">{e.external_id ?? "—"}</Text> },
    { key: "sync", label: "Estado", render: () => <Badge variant="dot" color="teal">Sincronizado</Badge> },
  ];

  const exportUrl = `/api/trades/executions.csv${qs(all)}`;

  return (
    <>
      <Group mb="sm" align="flex-end" wrap="wrap">
        <TextInput leftSection={<IconSearch size={14} />} placeholder="Pesquisar par ou ID" value={search} onChange={(e) => { setSearch(e.currentTarget.value); setPage(1); }} w={240} size="xs" label="Pesquisa" />
        <NumberInput size="xs" label="Valor mín." min={0} value={minV} onChange={(v) => { setMinV(v); setPage(1); }} w={120} />
        <NumberInput size="xs" label="Valor máx." min={0} value={maxV} onChange={(v) => { setMaxV(v); setPage(1); }} w={120} />
        <Button size="xs" variant="light" component="a" href={exportUrl} leftSection={<IconDownload size={14} />}>
          Exportar CSV
        </Button>
      </Group>
      {query.error && <ErrorAlert error={query.error} />}
      {query.isLoading ? (
        <Loading />
      ) : query.data && query.data.total === 0 ? (
        <EmptyState title="Nenhuma execução encontrada" description="Ajuste os filtros ou aguarde a próxima sincronização das suas integrações." />
      ) : (
        query.data && (
          <DataTable
            columns={cols}
            rows={query.data.items}
            rowKey={(e) => e.id}
            total={query.data.total}
            page={page}
            pageSize={pageSize}
            onPage={setPage}
            onPageSize={(n) => { setPageSize(n); setPage(1); }}
            sort={sort}
            direction={direction}
            onSort={(k, d) => { setSort(k); setDirection(d); }}
            minWidth={1300}
          />
        )
      )}
    </>
  );
}

function OrdersTab() {
  const { user } = useAuth();
  const params = useFilterParams();
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["orders", params, page],
    queryFn: () => api<Paged<Order>>(`/api/trades/orders${qs({ ...params, page, page_size: 25 })}`),
    placeholderData: keepPreviousData,
  });
  const cols: Column<Order>[] = [
    { key: "placed_at", label: "Criada em", render: (o) => fmtDate(o.placed_at, user?.timezone) },
    { key: "symbol", label: "Par", render: (o) => <Badge variant="outline">{o.symbol}</Badge> },
    { key: "side", label: "Lado", render: (o) => <SideBadge side={o.side} /> },
    { key: "type", label: "Tipo", render: (o) => o.type },
    { key: "status", label: "Estado", render: (o) => <Badge variant="light">{o.status}</Badge> },
    { key: "orig", label: "Qtd. ordem", align: "right", render: (o) => fmtNumber(o.orig_qty) },
    { key: "exec", label: "Qtd. executada", align: "right", render: (o) => fmtNumber(o.executed_qty) },
    { key: "quote", label: "Total executado", align: "right", render: (o) => fmtNumber(o.cumulative_quote_qty) },
    { key: "fills", label: "Execuções", align: "right", render: (o) => o.executions },
    { key: "ext", label: "ID externo", render: (o) => <Text size="xs" c="dimmed">{o.external_id}</Text> },
  ];
  if (query.isLoading) return <Loading />;
  if (!query.data?.total) return <EmptyState title="Nenhuma ordem" description="As ordens aparecem após a sincronização." />;
  return <DataTable columns={cols} rows={query.data.items} rowKey={(o) => o.id} total={query.data.total} page={page} pageSize={25} onPage={setPage} />;
}

function MovementsTab() {
  const { user } = useAuth();
  const params = useFilterParams();
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["movements", params, page],
    queryFn: () => api<Paged<Movement>>(`/api/trades/movements${qs({ ...params, page, page_size: 25 })}`),
  });
  const cols: Column<Movement>[] = [
    { key: "occurred_at", label: "Data", render: (m) => fmtDate(m.occurred_at, user?.timezone) },
    { key: "kind", label: "Tipo", render: (m) => <Badge color={m.kind === "deposit" ? "blue" : "grape"} variant="light">{m.kind === "deposit" ? "Depósito" : "Retirada"}</Badge> },
    { key: "asset", label: "Ativo", render: (m) => m.asset },
    { key: "amount", label: "Quantidade", align: "right", render: (m) => fmtNumber(m.amount) },
    { key: "fee", label: "Taxa", align: "right", render: (m) => (Number(m.fee) ? fmtNumber(m.fee) : "—") },
    { key: "network", label: "Rede", render: (m) => m.network ?? "—" },
    { key: "status", label: "Estado", render: (m) => <StatusBadge status={m.status === "completed" ? "succeeded" : m.status} /> },
    { key: "tx", label: "TxID", render: (m) => <Text size="xs" c="dimmed" maw={180} truncate>{m.tx_id ?? "—"}</Text> },
  ];
  if (query.isLoading) return <Loading />;
  if (!query.data?.total) return <EmptyState title="Nenhum depósito ou retirada" description="Movimentações aparecem quando a corretora as disponibiliza na API." />;
  return <DataTable columns={cols} rows={query.data.items} rowKey={(m) => m.id} total={query.data.total} page={page} pageSize={25} onPage={setPage} />;
}

export function OperationsPage() {
  const qc = useQueryClient();
  const globalParams = useFilterParams();
  const [rf, setRf] = useState<ResultFilters>(EMPTY_RESULT_FILTERS);
  // Mesmos filtros para tabela, indicadores, períodos e calendário.
  const params = { ...globalParams, side: undefined, ...resultParams(rf) };
  const summary = useQuery({
    queryKey: ["cycles-summary", params, "month"],
    queryFn: () => api<CycleSummary>(`/api/trades/cycles/summary${qs({ ...params, granularity: "month" })}`),
    placeholderData: keepPreviousData,
  });

  const refresh = useMutation({
    mutationFn: () => api("/api/trades/refresh-prices", { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries();
      notifications.show({ color: "teal", message: "Cotações atualizadas." });
    },
    onError: (e: Error) => notifications.show({ color: "red", message: e.message }),
  });

  return (
    <>
      <PageHeader
        title="Operações"
        description="Cada compra com a venda que a encerrou: valores na moeda e em BRL, lucro/prejuízo e %, com filtros por período e resultado."
        actions={
          <Group gap="xs">
            <SyncButton />
            <Menu position="bottom-end">
              <Menu.Target>
                <Button size="xs" variant="light" leftSection={<IconDownload size={14} />}>Exportar</Button>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Item component="a" href={`/api/trades/cycles.csv${qs(params)}`}>Compra e venda (CSV)</Menu.Item>
                <Menu.Item component="a" href={`/api/trades/executions.csv${qs(globalParams)}`}>Execuções (CSV)</Menu.Item>
              </Menu.Dropdown>
            </Menu>
            <Tooltip label="Atualiza as cotações das posições em aberto">
              <Button size="xs" variant="light" leftSection={<IconRefresh size={14} />} loading={refresh.isPending} onClick={() => refresh.mutate()}>
                Cotações
              </Button>
            </Tooltip>
          </Group>
        }
      />
      <FiltersBar showSide={false} />
      <ResultFiltersBar value={rf} onChange={setRf} />
      {summary.data && <SummaryCards s={summary.data} />}
      <Card withBorder radius="md">
        <Tabs defaultValue="buysell" keepMounted={false}>
          <Tabs.List mb="md">
            <Tabs.Tab value="buysell">Compra e venda</Tabs.Tab>
            <Tabs.Tab value="periods">Por período</Tabs.Tab>
            <Tabs.Tab value="calendar">Calendário</Tabs.Tab>
            <Tabs.Tab value="assets">Por ativo</Tabs.Tab>
            <Tabs.Tab value="executions">Execuções</Tabs.Tab>
            <Tabs.Tab value="orders">Ordens</Tabs.Tab>
            <Tabs.Tab value="movements">Depósitos e retiradas</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="buysell">
            <CyclesTable params={params} />
          </Tabs.Panel>
          <Tabs.Panel value="periods">
            <PeriodsPanel params={params} />
          </Tabs.Panel>
          <Tabs.Panel value="calendar">
            <CalendarPanel params={params} />
          </Tabs.Panel>
          <Tabs.Panel value="assets">
            <AssetsPanel s={summary.data} />
          </Tabs.Panel>
          <Tabs.Panel value="executions">
            <InfoNote>Execuções individuais (fills) como vieram da corretora. Uma ordem pode gerar várias execuções.</InfoNote>
            <ExecutionsTab />
          </Tabs.Panel>
          <Tabs.Panel value="orders">
            <InfoNote>Ordens não são contadas como operações concluídas: o resultado é apurado a partir das execuções.</InfoNote>
            <OrdersTab />
          </Tabs.Panel>
          <Tabs.Panel value="movements">
            <InfoNote>Depósitos e retiradas não são lucro nem prejuízo. Transferências entre suas próprias contas preservam o custo original.</InfoNote>
            <MovementsTab />
          </Tabs.Panel>
        </Tabs>
      </Card>
    </>
  );
}
