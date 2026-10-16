import { Button, Group, Text, Tooltip } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconRefresh } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "../api/client";
import type { Connection } from "../api/types";
import { relative } from "../lib/format";

interface SyncAllResp {
  queued: { id: string; name: string }[];
  skipped: { id: string; name: string; status: string }[];
}

/** Agenda a sincronização de todas as conexões e atualiza as telas quando termina. */
export function SyncButton() {
  const qc = useQueryClient();
  const conns = useQuery({
    queryKey: ["connections"],
    queryFn: () => api<Connection[]>("/api/integrations/connections"),
    refetchInterval: (q) => ((q.state.data ?? []).some((c) => c.current_job) ? 3000 : 60_000),
  });
  const list = conns.data ?? [];
  const busy = list.some((c) => c.current_job);
  const wasBusy = useRef(false);

  useEffect(() => {
    if (wasBusy.current && !busy) {
      // Sincronização terminou: recarrega operações, saldos e resultados.
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "connections" });
      const failed = list.filter((c) => c.status === "error" || c.status === "invalid_credentials");
      notifications.show(
        failed.length
          ? { color: "orange", title: "Sincronização concluída com falhas", message: failed.map((c) => `${c.name}: ${c.status_message ?? c.status}`).join(" · ") }
          : { color: "teal", message: "Sincronização concluída." },
      );
    }
    wasBusy.current = busy;
  }, [busy, list, qc]);

  const sync = useMutation({
    mutationFn: () => api<SyncAllResp>("/api/integrations/sync-all", { method: "POST" }),
    onSuccess: (r) => {
      wasBusy.current = r.queued.length > 0;
      if (r.queued.length) notifications.show({ color: "blue", message: `Sincronizando ${r.queued.length} conexão(ões)…` });
      if (r.skipped.length)
        notifications.show({ color: "orange", message: `Ignoradas (suspensas ou com credencial inválida): ${r.skipped.map((s) => s.name).join(", ")}` });
      void qc.invalidateQueries({ queryKey: ["connections"] });
    },
    onError: (e: Error) => notifications.show({ color: "red", message: e.message }),
  });

  const last = list.map((c) => c.last_successful_sync_at).filter(Boolean).sort().pop() ?? null;
  const disabled = !list.length;

  return (
    <Group gap="xs" wrap="nowrap">
      <Text size="xs" c="dimmed" visibleFrom="sm">
        {busy ? "Sincronizando…" : `Última: ${relative(last)}`}
      </Text>
      <Tooltip label="Cadastre uma integração para sincronizar" disabled={!disabled}>
        <Button
          size="xs"
          leftSection={<IconRefresh size={14} />}
          loading={busy || sync.isPending}
          disabled={disabled}
          onClick={() => sync.mutate()}
        >
          Sincronizar
        </Button>
      </Tooltip>
    </Group>
  );
}
