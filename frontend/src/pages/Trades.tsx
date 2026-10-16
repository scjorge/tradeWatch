import { Badge, Button, Card, Group, SegmentedControl, SimpleGrid, Table, Text, Title, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconRefresh } from "@tabler/icons-react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, qs } from "../api/client";
import type { Paged, PositionRow, RealizedRecord, RealizedSummary } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { DEFAULT_CURRENCY } from "../lib/currency";
import { DataTable, type Column } from "../components/DataTable";
import { useFilterParams } from "../components/FiltersContext";
import { FiltersBar } from "../components/FiltersBar";
import { EmptyState, InfoNote, Loading, Money, PageHeader, StatCard, StatusBadge } from "../components/common";
import { fmtDate, fmtMoney, fmtNumber, fmtPct, signColor } from "../lib/format";

interface PositionsResp {
  base_currency: string;
  method: string;
  positions: PositionRow[];
  unrealized_total: string;
  unrealized_complete: boolean;
  open_cost_basis: string;
}

const KIND: Record<string, string> = { sale: "Venda", conversion: "Conversão", fee: "Taxa em outro ativo" };

export function TradesPage() {
  const { user } = useAuth();
  const params = useFilterParams();
  const qc = useQueryClient();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const positions = useQuery({ queryKey: ["positions"], queryFn: () => api<PositionsResp>("/api/trades/positions") });
  const summary = useQuery({ queryKey: ["pnl-summary", params], queryFn: () => api<RealizedSummary>(`/api/trades/pnl/summary${qs(params)}`) });
  const records = useQuery({
    queryKey: ["realized", params, status, page],
    queryFn: () => api<Paged<RealizedRecord>>(`/api/trades/pnl/realized${qs({ ...params, status, page, page_size: 25 })}`),
    placeholderData: keepPreviousData,
  });
  const recalc = useMutation({
    mutationFn: () => api("/api/trades/recalculate", { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries();
      notifications.show({ message: "Apuração recalculada com as cotações em cache.", color: "teal" });
    },
  });

  const r = user?.base_currency ?? DEFAULT_CURRENCY;
  const s = summary.data;

  const cols: Column<RealizedRecord>[] = [
    { key: "at", label: "Data", render: (x) => fmtDate(x.realized_at, user?.timezone) },
    { key: "kind", label: "Tipo", render: (x) => KIND[x.kind] ?? x.kind },
    { key: "asset", label: "Ativo", render: (x) => x.asset },
    { key: "qty", label: "Quantidade", align: "right", render: (x) => fmtNumber(x.quantity) },
    { key: "proceeds", label: "Receita", align: "right", render: (x) => <Money value={x.proceeds} currency={x.base_currency} /> },
    { key: "cost", label: "Custo", align: "right", render: (x) => <Money value={x.cost_basis} currency={x.base_currency} /> },
    { key: "pnl", label: "Resultado", align: "right", render: (x) => <Money value={x.realized_pnl} currency={x.base_currency} colored /> },
    {
      key: "status",
      label: "Situação",
      render: (x) => (
        <Tooltip label={x.note ?? "Custo e cotação conhecidos"} multiline w={300}>
          <span>
            <StatusBadge status={x.status} />
          </span>
        </Tooltip>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Trades"
        description={`Posições e resultados apurados pelo método ${user?.cost_method === "AVERAGE" ? "de custo médio" : "FIFO"} em ${r}. Altere o método em Configurações.`}
        actions={
          <Button variant="light" size="xs" leftSection={<IconRefresh size={14} />} loading={recalc.isPending} onClick={() => recalc.mutate()}>
            Recalcular
          </Button>
        }
      />
      <FiltersBar />
      {s && (
        <SimpleGrid cols={{ base: 2, md: 4 }} mb="md">
          <StatCard label="Realizado líquido" value={<Money value={s.realized_net} currency={r} colored />} color={signColor(s.realized_net)} incomplete={s.records_incomplete ? `${s.records_incomplete} registro(s) incompleto(s) fora da soma` : undefined} />
          <StatCard label="Realizado bruto" value={<Money value={s.realized_gross} currency={r} />} hint="Líquido + taxas pagas no período" />
          <StatCard label="Taxas pagas" value={<Money value={s.fees_paid} currency={r} />} incomplete={s.fees_complete ? undefined : "Algumas taxas sem cotação"} />
          <StatCard label="Não realizado" value={<Money value={positions.data?.unrealized_total ?? null} currency={r} colored />} incomplete={positions.data && !positions.data.unrealized_complete ? "Posições com custo desconhecido não entram" : undefined} />
        </SimpleGrid>
      )}

      <Card withBorder radius="md" mb="md">
        <Title order={5} mb="sm">
          Posições abertas
        </Title>
        {positions.isLoading ? (
          <Loading />
        ) : !positions.data?.positions.length ? (
          <EmptyState title="Sem posições" description="As posições são calculadas a partir das execuções e movimentações sincronizadas." />
        ) : (
          <Table.ScrollContainer minWidth={1000}>
            <Table striped fz="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Ativo</Table.Th>
                  <Table.Th ta="right">Qtd. calculada</Table.Th>
                  <Table.Th ta="right">Qtd. na corretora</Table.Th>
                  <Table.Th ta="right">Custo médio</Table.Th>
                  <Table.Th ta="right">Custo total</Table.Th>
                  <Table.Th ta="right">Cotação</Table.Th>
                  <Table.Th ta="right">Valor de mercado</Table.Th>
                  <Table.Th ta="right">Não realizado</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {positions.data.positions.map((p) => (
                  <Table.Tr key={p.asset}>
                    <Table.Td>
                      <Group gap={6}>
                        <Text fw={600} size="sm">{p.asset}</Text>
                        {!p.cost_basis_complete && (
                          <Tooltip label={`${fmtNumber(p.unknown_cost_quantity)} ${p.asset} com custo desconhecido (depósito externo ou histórico ausente).`} multiline w={260}>
                            <Badge size="xs" color="yellow" variant="light">custo parcial</Badge>
                          </Tooltip>
                        )}
                      </Group>
                    </Table.Td>
                    <Table.Td ta="right">{fmtNumber(p.quantity)}</Table.Td>
                    <Table.Td ta="right">
                      {p.reported_quantity ? fmtNumber(p.reported_quantity) : "—"}
                      {p.difference && Number(p.difference) !== 0 && (
                        <Tooltip label="Diferença entre saldo informado pela corretora e o calculado pelo histórico. Pode indicar histórico incompleto (Earn, Convert, dust).">
                          <Text span size="xs" c="orange" ml={4}>
                            Δ {fmtNumber(p.difference)}
                          </Text>
                        </Tooltip>
                      )}
                    </Table.Td>
                    <Table.Td ta="right"><Money value={p.avg_cost} currency={r} /></Table.Td>
                    <Table.Td ta="right"><Money value={p.cost_basis} currency={r} /></Table.Td>
                    <Table.Td ta="right">
                      <Tooltip label={p.price_source ? `${p.price_source} · ${fmtDate(p.price_at, user?.timezone)}` : "Sem cotação"}>
                        <span>{fmtMoney(p.price, r)}</span>
                      </Tooltip>
                    </Table.Td>
                    <Table.Td ta="right"><Money value={p.market_value} currency={r} /></Table.Td>
                    <Table.Td ta="right">
                      {p.asset === r ? (
                        "—"
                      ) : (
                        <>
                          <Money value={p.unrealized_pnl} currency={r} colored />{" "}
                          {p.unrealized_pct !== null && <Text span size="xs" c={signColor(p.unrealized_pct)}>({fmtPct(p.unrealized_pct)})</Text>}
                        </>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Card>

      <Card withBorder radius="md">
        <Group justify="space-between" mb="sm">
          <Title order={5}>Resultados realizados</Title>
          <SegmentedControl
            size="xs"
            value={status}
            onChange={(v) => { setStatus(v); setPage(1); }}
            data={[
              { label: "Todos", value: "" },
              { label: "Completos", value: "complete" },
              { label: "Incompletos", value: "incomplete" },
            ]}
          />
        </Group>
        <InfoNote>
          Registros "incompletos" não têm custo ou cotação confiáveis (ex.: ativo depositado de fora ou histórico indisponível na API). Eles
          não entram nas somas. Se o ativo foi negociado em pares já zerados, inclua-os em "Pares adicionais" na integração.
        </InfoNote>
        {records.data && records.data.total > 0 ? (
          <DataTable columns={cols} rows={records.data.items} rowKey={(x) => x.id} total={records.data.total} page={page} pageSize={25} onPage={setPage} />
        ) : records.isLoading ? (
          <Loading />
        ) : (
          <EmptyState title="Nenhum resultado no período" description="Resultados realizados surgem quando há vendas ou conversões." />
        )}
      </Card>
    </>
  );
}
