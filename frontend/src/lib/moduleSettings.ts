import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { notifications } from "@mantine/notifications";
import { api } from "../api/client";

type Settings = Record<string, unknown>;

/** Preferências do usuário por módulo, salvas no perfil (servidor) e não no navegador. */
export function useModuleSettings(moduleKey: string, enabled = true) {
  const qc = useQueryClient();
  const key = ["module-settings", moduleKey];
  const query = useQuery({
    queryKey: key,
    queryFn: () => api<{ settings: Settings }>(`/api/me/modules/${moduleKey}/settings`).then((r) => r.settings),
    staleTime: Infinity,
    enabled,
  });
  const mutation = useMutation({
    mutationFn: (patch: Settings) => api<{ settings: Settings }>(`/api/me/modules/${moduleKey}/settings`, { method: "PATCH", body: { settings: patch } }),
    // Atualização otimista: a tela muda na hora; se o servidor recusar, volta ao estado anterior.
    onMutate: async (patch) => {
      await qc.cancelQueries({ queryKey: key });
      const previous = qc.getQueryData<Settings>(key);
      qc.setQueryData<Settings>(key, { ...(previous ?? {}), ...patch });
      return { previous };
    },
    onError: (e: Error, _patch, ctx) => {
      qc.setQueryData(key, ctx?.previous);
      notifications.show({ color: "red", message: `Não foi possível salvar a preferência: ${e.message}` });
    },
    onSuccess: (r) => qc.setQueryData(key, r.settings),
  });
  return { settings: query.data, loaded: query.isSuccess, failed: query.isError, save: mutation.mutate };
}
