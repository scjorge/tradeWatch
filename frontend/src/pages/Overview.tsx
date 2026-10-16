import { AreaChart, BarChart, DonutChart } from "@mantine/charts";
import { Anchor, Badge, Button, Card, Group, SimpleGrid, Stack, Table, Text, Title } from "@mantine/core";
import { IconPlug } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, qs } from "../api/client";
import type { Dashboard } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useFilterParams } from "../components/FiltersContext";
import { FiltersBar } from "../components/FiltersBar";
import { SyncButton } from "../components/SyncButton";
import { EmptyState, ErrorAlert, Loading, Money, PageHeader, SideBadge, StatCard, StatusBadge } from "../components/common";
import { fmtDate, fmtMoney, fmtNumber, fmtPct, relative, signColor } from "../lib/format";

const PALETTE = ["blue.6", "teal.6", "violet.6", "orange.6", "cyan.6", "pink.6", "lime.6", "gray.6"];

export function OverviewPage() {
  const params = useFilterParams();
  const { user } = useAuth();
  const q = useQuery({ queryKey: ["dashboard", params], queryFn: () => api<Dashboard>(`/api/dashboard${qs(params)}`), refetchInterval: 60_000 });

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorAlert error={q.error} />;
  const d = q.data!;
  const r = d.base_currency;
  const tz = user?.timezone;

  if (d.integrations.length === 0)
    return (
      <>
        <PageHeader title="Visão geral" />
        <EmptyState
          title="Nenhuma integração ainda"
          description="Conecte sua conta da Binance com uma chave somente leitura para ver saldos, operações e resultados."
          action={
            <Button component={Link} to="/integrations" leftSection={<IconPlug size={16} />}>
              Adicionar integração
            </Button>
          }
        />
      </>
    );

  const s = d.realized;
  const distribution = d.holdings.by_asset
    .filter((a) => a.value && Number(a.value) > 0)
    .slice(0, 7)
    .map((a, i) => ({ name: a.asset, value: Number(a.value), color: PALETTE[i % PALETTE.length] }));
  const rest = d.holdings.by_asset.filter((a) => a.value && Number(a.value) > 0).slice(7);
  if (rest.length) distribution.push({ name: "Outros", value: rest.reduce((acc, a) => acc + Number(a.value), 0), color: "gray.5" });

  return (
    <>
      <PageHeader
        title="Visão geral"
        description={`Valores em ${r} · método de custo ${d.method === "FIFO" ? "FIFO" : "custo médio"} · última sincronização ${relative(d.last_sync_at)}`}
        actions={<SyncButton />}
      />
      <FiltersBar />
      <SimpleGrid cols={{ base: 1, xs: 2, md: 4 }} mb="md">
        <StatCard
          label="Patrimônio acompanhado"
          value={<Money value={d.holdings.total_value} currency={r} />}
          hint="Saldo atual informado pela corretora × cotação mais recente"
          incomplete={d.holdings.complete ? undefined : `Sem cotação para: ${d.holdings.unpriced_assets.join(", ")}`}
        />
        <StatCard
          label="Resultado realizado (líquido)"
          value={<Money value={s.realized_net} currency={r} colored />}
          color={signColor(s.realized_net)}
          hint={`Bruto ${fmtMoney(s.realized_gross, r)} · taxas ${fmtMoney(s.fees_paid, r)}`}
          incomplete={s.records_incomplete ? `${s.records_incomplete} registro(s) sem custo ou cotação — excluídos da soma` : undefined}
        />
        <StatCard
          label="Resultado não realizado"
          value={<Money value={d.unrealized.total} currency={r} colored />}
          color={signColor(d.unrealized.total)}
          hint={`Sobre custo em aberto de ${fmtMoney(d.unrealized.open_cost_basis, r)}`}
          incomplete={d.unrealized.complete ? undefined : "Há posições com custo desconhecido ou sem cotação"}
        />
        <StatCard label="Rentabilidade realizada" value={fmtPct(s.realized_return_pct)} color={signColor(s.realized_return_pct ?? undefined)} hint="Resultado líquido ÷ custo das posições encerradas" />
      </SimpleGrid>
      <SimpleGrid cols={{ base: 2, md: 4 }} mb="md">
        <StatCard label="Execuções" value={fmtNumber(s.executions_count)} hint={`${s.closed_operations} venda(s) com resultado`} />
        <StatCard label="Operações lucrativas" value={fmtPct(s.win_rate_pct)} />
        <StatCard label="Ganho médio / perda média" value={<Text span inherit>{fmtMoney(s.avg_gain, r)}</Text>} hint={`Perda média: ${fmtMoney(s.avg_loss, r)}`} />
        <StatCard
          label="Melhor / pior operação"
          value={<Money value={s.best?.realized_pnl ?? null} currency={r} colored />}
          hint={s.worst ? `Pior: ${fmtMoney(s.worst.realized_pnl, r)} (${s.worst.asset})` : "—"}
        />
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, lg: 3 }} mb="md">
        <Card withBorder radius="md" style={{ gridColumn: "span 2" }}>
          <Title order={5} mb="sm">
            Evolução do patrimônio
          </Title>
          {d.equity_history.length < 2 ? (
            <Text c="dimmed" size="sm">
              O histórico é formado pelos snapshots de cada sincronização. Volte depois de algumas sincronizações.
            </Text>
          ) : (
            <AreaChart
              h={240}
              data={d.equity_history.map((p) => ({ date: p.date.slice(5), Patrimônio: Number(p.value) }))}
              dataKey="date"
              series={[{ name: "Patrimônio", color: "blue.6" }]}
              curveType="monotone"
              withDots={false}
              valueFormatter={(v) => fmtMoney(v, r)}
            />
          )}
          <Text size="xs" c="dimmed" mt="xs">
            Variação de patrimônio inclui aportes e retiradas — não confundir com lucro.
          </Text>
        </Card>
        <Card withBorder radius="md">
          <Title order={5} mb="sm">
            Distribuição dos ativos
          </Title>
          {distribution.length ? (
            <Group justify="center">
              <DonutChart data={distribution} size={180} thickness={26} withTooltip tooltipDataSource="segment" valueFormatter={(v) => fmtMoney(v, r)} />
            </Group>
          ) : (
            <Text c="dimmed" size="sm">
              Sem saldos com cotação.
            </Text>
          )}
          <Stack gap={2} mt="sm">
            {distribution.map((x) => (
              <Group key={x.name} justify="space-between">
                <Text size="sm">{x.name}</Text>
                <Text size="sm" c="dimmed">
                  {fmtPct((x.value / Number(d.holdings.total_value || 1)) * 100)}
                </Text>
              </Group>
            ))}
          </Stack>
        </Card>
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, lg: 2 }} mb="md">
        <Card withBorder radius="md">
          <Title order={5} mb="sm">
            Resultado realizado por período
          </Title>
          {d.pnl_by_period.length ? (
            <BarChart
              h={220}
              data={d.pnl_by_period.map((p) => ({ period: p.period, Resultado: Number(p.realized) }))}
              dataKey="period"
              series={[{ name: "Resultado", color: "teal.6" }]}
              valueFormatter={(v) => fmtMoney(v, r)}
              getBarColor={(v) => (v >= 0 ? "teal.6" : "red.6")}
            />
          ) : (
            <Text c="dimmed" size="sm">
              Nenhuma venda no período.
            </Text>
          )}
        </Card>
        <Card withBorder radius="md">
          <Group justify="space-between" mb="sm">
            <Title order={5}>Integrações</Title>
            <Anchor component={Link} to="/integrations" size="sm">
              Gerenciar
            </Anchor>
          </Group>
          <Stack gap="xs">
            {d.integrations.map((c) => (
              <Group key={c.id} justify="space-between" wrap="nowrap">
                <div>
                  <Text size="sm" fw={500}>
                    {c.name}
                  </Text>
                  <Text size="xs" c="dimmed">
                    Última sincronização: {relative(c.last_successful_sync_at)}
                  </Text>
                </div>
                <StatusBadge status={c.status} />
              </Group>
            ))}
          </Stack>
        </Card>
      </SimpleGrid>

      <Card withBorder radius="md">
        <Group justify="space-between" mb="sm">
          <Title order={5}>Atividade recente</Title>
          <Anchor component={Link} to="/operations" size="sm">
            Ver todas
          </Anchor>
        </Group>
        {d.recent_activity.length === 0 ? (
          <Text c="dimmed" size="sm">
            Nenhuma execução sincronizada ainda.
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={560}>
            <Table striped highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Data</Table.Th>
                  <Table.Th>Conta</Table.Th>
                  <Table.Th>Par</Table.Th>
                  <Table.Th>Lado</Table.Th>
                  <Table.Th ta="right">Quantidade</Table.Th>
                  <Table.Th ta="right">Valor</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {d.recent_activity.map((a) => (
                  <Table.Tr key={a.id}>
                    <Table.Td>{fmtDate(a.executed_at, tz)}</Table.Td>
                    <Table.Td>{a.connection_name}</Table.Td>
                    <Table.Td>
                      <Badge variant="outline">{a.symbol}</Badge>
                    </Table.Td>
                    <Table.Td>
                      <SideBadge side={a.side} />
                    </Table.Td>
                    <Table.Td ta="right">{fmtNumber(a.quantity)}</Table.Td>
                    <Table.Td ta="right">{fmtMoney(a.quote_quantity, a.quote_asset)}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Card>
    </>
  );
}
