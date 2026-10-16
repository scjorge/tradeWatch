import { AreaChart } from "@mantine/charts";
import { Button, Card, Group, SimpleGrid, Table, Text, Title, Tooltip } from "@mantine/core";
import { DatePickerInput } from "@mantine/dates";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, qs } from "../api/client";
import type { EquityPoint, Holdings } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useFilterParams } from "../components/FiltersContext";
import { FiltersBar } from "../components/FiltersBar";
import { EmptyState, ErrorAlert, InfoNote, Loading, Money, PageHeader, StatCard } from "../components/common";
import { fmtDate, fmtMoney, fmtNumber, fmtPct, signColor } from "../lib/format";

interface CompareResp {
  base_currency: string;
  a: EquityPoint | null;
  b: EquityPoint | null;
  change: string | null;
  change_pct: number | null;
  note: string;
}

export function PortfolioPage() {
  const { user } = useAuth();
  const params = useFilterParams();
  const r = user?.base_currency ?? "USDT";
  const balances = useQuery({ queryKey: ["balances", params], queryFn: () => api<Holdings>(`/api/portfolio/balances${qs(params)}`) });
  const history = useQuery({ queryKey: ["history", params], queryFn: () => api<{ items: EquityPoint[] }>(`/api/portfolio/history${qs(params)}`) });
  const [range, setRange] = useState<[Date | null, Date | null]>([null, null]);
  const compare = useQuery({
    queryKey: ["compare", range],
    enabled: !!range[0] && !!range[1],
    queryFn: () => api<CompareResp>(`/api/portfolio/compare${qs({ a: range[0]!.toISOString(), b: range[1]!.toISOString() })}`),
  });

  if (balances.isLoading) return <Loading />;
  if (balances.error) return <ErrorAlert error={balances.error} />;
  const h = balances.data!;

  return (
    <>
      <PageHeader title="Carteiras e saldos" description="Saldos informados pelas corretoras, valorizados pela cotação mais recente. A fonte e o horário da cotação aparecem em cada linha." />
      <FiltersBar showSide={false} />
      {h.rows.length === 0 ? (
        <EmptyState title="Sem saldos" description="Os saldos aparecem após a primeira sincronização de uma integração." />
      ) : (
        <>
          <SimpleGrid cols={{ base: 1, sm: 3 }} mb="md">
            <StatCard label="Valor estimado" value={<Money value={h.total_value} currency={r} />} incomplete={h.complete ? undefined : `Sem cotação: ${h.unpriced_assets.join(", ")}`} />
            {h.by_connection.slice(0, 2).map((c) => (
              <StatCard key={c.connection_id} label={c.name} value={<Money value={c.value} currency={r} />} hint={c.provider} />
            ))}
          </SimpleGrid>

          <SimpleGrid cols={{ base: 1, lg: 2 }} mb="md">
            <Card withBorder radius="md">
              <Title order={5} mb="sm">Por ativo</Title>
              <Table fz="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Ativo</Table.Th>
                    <Table.Th ta="right">Quantidade</Table.Th>
                    <Table.Th ta="right">Valor estimado</Table.Th>
                    <Table.Th ta="right">% carteira</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {h.by_asset.map((a) => (
                    <Table.Tr key={a.asset}>
                      <Table.Td fw={600}>{a.asset}</Table.Td>
                      <Table.Td ta="right">{fmtNumber(a.quantity)}</Table.Td>
                      <Table.Td ta="right"><Money value={a.value} currency={r} /></Table.Td>
                      <Table.Td ta="right">{fmtPct(a.share_pct)}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Card>
            <Card withBorder radius="md">
              <Title order={5} mb="sm">Evolução histórica</Title>
              {history.data && history.data.items.length > 1 ? (
                <AreaChart
                  h={260}
                  data={history.data.items.map((p) => ({ date: p.date.slice(5), Valor: Number(p.value) }))}
                  dataKey="date"
                  series={[{ name: "Valor", color: "blue.6" }]}
                  withDots={false}
                  curveType="monotone"
                  valueFormatter={(v) => fmtMoney(v, r)}
                />
              ) : (
                <Text size="sm" c="dimmed">Snapshots periódicos formam este gráfico; ele não depende do histórico antigo da corretora.</Text>
              )}
            </Card>
          </SimpleGrid>

          <Card withBorder radius="md" mb="md">
            <Title order={5} mb="sm">Comparar períodos</Title>
            <Group align="flex-end">
              <DatePickerInput type="range" label="Datas" placeholder="De / até" value={range} onChange={setRange} valueFormat="DD/MM/YYYY" w={260} />
              <Button variant="subtle" onClick={() => setRange([null, null])}>Limpar</Button>
            </Group>
            {compare.data && (
              <Group mt="md" gap="xl">
                <Text size="sm">{compare.data.a?.date ?? "—"}: <b>{fmtMoney(compare.data.a?.value ?? null, r)}</b></Text>
                <Text size="sm">{compare.data.b?.date ?? "—"}: <b>{fmtMoney(compare.data.b?.value ?? null, r)}</b></Text>
                <Text size="sm" c={signColor(compare.data.change)}>Variação: <b>{fmtMoney(compare.data.change, r)} ({fmtPct(compare.data.change_pct)})</b></Text>
                <Text size="xs" c="dimmed">{compare.data.note}</Text>
              </Group>
            )}
          </Card>

          <Card withBorder radius="md">
            <Title order={5} mb="sm">Saldos por conta</Title>
            <InfoNote>Saldo informado pela corretora (livre + bloqueado). O saldo calculado localmente a partir do histórico aparece em Trades → Posições.</InfoNote>
            <Table.ScrollContainer minWidth={900}>
              <Table striped fz="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Conta</Table.Th>
                    <Table.Th>Ativo</Table.Th>
                    <Table.Th ta="right">Livre</Table.Th>
                    <Table.Th ta="right">Bloqueado</Table.Th>
                    <Table.Th ta="right">Total</Table.Th>
                    <Table.Th ta="right">Cotação</Table.Th>
                    <Table.Th ta="right">Valor estimado</Table.Th>
                    <Table.Th>Atualizado</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {h.rows.map((b) => (
                    <Table.Tr key={`${b.connection_id}-${b.asset}`}>
                      <Table.Td>{b.connection_name}</Table.Td>
                      <Table.Td fw={600}>{b.asset}</Table.Td>
                      <Table.Td ta="right">{fmtNumber(b.free)}</Table.Td>
                      <Table.Td ta="right">{fmtNumber(b.locked)}</Table.Td>
                      <Table.Td ta="right">{fmtNumber(b.total)}</Table.Td>
                      <Table.Td ta="right">
                        <Tooltip label={b.price_source ? `${b.price_source} · ${fmtDate(b.price_at, user?.timezone)}` : "Sem cotação disponível"}>
                          <span>{fmtMoney(b.price, r)}</span>
                        </Tooltip>
                      </Table.Td>
                      <Table.Td ta="right"><Money value={b.value} currency={r} /></Table.Td>
                      <Table.Td>{fmtDate(b.reported_at, user?.timezone)}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          </Card>
        </>
      )}
    </>
  );
}
