import { BarChart } from "@mantine/charts";
import { Button, Card, Group, SegmentedControl, Table, Text, Title } from "@mantine/core";
import { IconDownload } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, qs } from "../api/client";
import type { PeriodPnl } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useFilterParams } from "../components/FiltersContext";
import { FiltersBar } from "../components/FiltersBar";
import { EmptyState, Loading, Money, PageHeader } from "../components/common";
import { fmtMoney } from "../lib/format";

export function ReportsPage() {
  const { user } = useAuth();
  const params = useFilterParams();
  const [granularity, setGranularity] = useState("month");
  const r = user?.base_currency ?? "USDT";
  const q = useQuery({
    queryKey: ["by-period", params, granularity],
    queryFn: () => api<{ items: PeriodPnl[] }>(`/api/trades/pnl/by-period${qs({ ...params, granularity })}`),
  });

  const items = q.data?.items ?? [];
  const totalRealized = items.reduce((a, x) => a + Number(x.realized), 0);
  const totalFees = items.reduce((a, x) => a + Number(x.fees), 0);

  return (
    <>
      <PageHeader
        title="Relatórios"
        description="Resultado realizado e taxas por período, no fuso horário configurado."
        actions={
          <Button size="xs" variant="light" component="a" href={`/api/trades/executions.csv${qs(params)}`} leftSection={<IconDownload size={14} />}>
            Exportar operações (CSV)
          </Button>
        }
      />
      <FiltersBar />
      <Card withBorder radius="md">
        <Group justify="space-between" mb="md">
          <Title order={5}>Resultado por período</Title>
          <SegmentedControl
            size="xs"
            value={granularity}
            onChange={setGranularity}
            data={[
              { label: "Dia", value: "day" },
              { label: "Semana", value: "week" },
              { label: "Mês", value: "month" },
            ]}
          />
        </Group>
        {q.isLoading ? (
          <Loading />
        ) : items.length === 0 ? (
          <EmptyState title="Sem resultados no período" description="Ajuste os filtros ou aguarde novas operações." />
        ) : (
          <>
            <BarChart
              h={260}
              mb="md"
              data={items.map((p) => ({ period: p.period, Resultado: Number(p.realized), Taxas: -Number(p.fees) }))}
              dataKey="period"
              series={[
                { name: "Resultado", color: "teal.6" },
                { name: "Taxas", color: "orange.5" },
              ]}
              valueFormatter={(v) => fmtMoney(v, r)}
            />
            <Table.ScrollContainer minWidth={600}>
              <Table striped fz="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Período</Table.Th>
                    <Table.Th ta="right">Vendas</Table.Th>
                    <Table.Th ta="right">Resultado líquido</Table.Th>
                    <Table.Th ta="right">Taxas</Table.Th>
                    <Table.Th ta="right">Registros incompletos</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {items.map((p) => (
                    <Table.Tr key={p.period}>
                      <Table.Td>{p.period}</Table.Td>
                      <Table.Td ta="right">{p.operations}</Table.Td>
                      <Table.Td ta="right"><Money value={p.realized} currency={r} colored /></Table.Td>
                      <Table.Td ta="right">{fmtMoney(p.fees, r)}</Table.Td>
                      <Table.Td ta="right">{p.incomplete || "—"}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
                <Table.Tfoot>
                  <Table.Tr>
                    <Table.Th>Total</Table.Th>
                    <Table.Th />
                    <Table.Th ta="right"><Money value={String(totalRealized)} currency={r} colored /></Table.Th>
                    <Table.Th ta="right">{fmtMoney(totalFees, r)}</Table.Th>
                    <Table.Th />
                  </Table.Tr>
                </Table.Tfoot>
              </Table>
            </Table.ScrollContainer>
            <Text size="xs" c="dimmed" mt="sm">
              Os totais do rodapé são somas de exibição; os valores por período vêm do servidor com precisão decimal.
            </Text>
          </>
        )}
      </Card>
    </>
  );
}
