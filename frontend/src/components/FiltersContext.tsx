import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useAuth } from "../auth/AuthContext";
import { useModuleSettings } from "../lib/moduleSettings";
import { Loading } from "./common";

export type Period = "month" | "prevmonth" | "ytd" | "7d" | "30d" | "90d" | "1y" | "all" | "custom";

export interface GlobalFilters {
  period: Period;
  range: [Date | null, Date | null];
  connectionIds: string[];
  asset: string;
  side: "" | "BUY" | "SELL";
  market: string;
  provider: string;
}

export const DEFAULT_FILTERS: GlobalFilters = { period: "90d", range: [null, null], connectionIds: [], asset: "", side: "", market: "", provider: "" };
const PREF_KEY = "global_filters";
const LEGACY_LOCAL_KEY = "tw.filters";
const PERIODS: Period[] = ["month", "prevmonth", "ytd", "7d", "30d", "90d", "1y", "all", "custom"];

const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const fromYmd = (v: unknown) => (typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) ? new Date(`${v}T00:00:00`) : null);

/** Formato salvo no perfil: datas como AAAA-MM-DD (sem fuso), demais campos como estão. */
export function serializeFilters(f: GlobalFilters) {
  return { ...f, range: [f.range[0] ? ymd(f.range[0]) : null, f.range[1] ? ymd(f.range[1]) : null] };
}

export function deserializeFilters(raw: unknown): GlobalFilters {
  if (!raw || typeof raw !== "object") return DEFAULT_FILTERS;
  const v = raw as Record<string, unknown>;
  const range = Array.isArray(v.range) ? v.range : [];
  return {
    period: PERIODS.includes(v.period as Period) ? (v.period as Period) : DEFAULT_FILTERS.period,
    range: [fromYmd(range[0]), fromYmd(range[1])],
    connectionIds: Array.isArray(v.connectionIds) ? v.connectionIds.filter((x): x is string => typeof x === "string") : [],
    asset: typeof v.asset === "string" ? v.asset : "",
    side: v.side === "BUY" || v.side === "SELL" ? v.side : "",
    market: typeof v.market === "string" ? v.market : "",
    provider: typeof v.provider === "string" ? v.provider : "",
  };
}

const Ctx = createContext<{ filters: GlobalFilters; setFilters: (f: Partial<GlobalFilters>) => void; reset: () => void } | null>(null);

/** Filtros globais (período, conta, ativo…) salvos no perfil do usuário, não no navegador. */
export function FiltersProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const prefs = useModuleSettings("core", !!user);
  const [filters, set] = useState<GlobalFilters>(DEFAULT_FILTERS);
  const current = useRef(filters);
  const hydratedFor = useRef<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    // Versões anteriores guardavam os filtros no navegador; remove a cópia local.
    try {
      localStorage.removeItem(LEGACY_LOCAL_KEY);
    } catch {
      /* armazenamento indisponível */
    }
  }, []);

  useEffect(() => {
    if (!user) {
      hydratedFor.current = null;
      current.current = DEFAULT_FILTERS;
      set(DEFAULT_FILTERS);
      return;
    }
    if (hydratedFor.current !== user.id && (prefs.loaded || prefs.failed)) {
      const loaded = deserializeFilters(prefs.settings?.[PREF_KEY]);
      hydratedFor.current = user.id;
      current.current = loaded;
      set(loaded);
    }
  }, [user, prefs.loaded, prefs.failed, prefs.settings]);

  const setFilters = (patch: Partial<GlobalFilters>) => {
    const next = { ...current.current, ...patch };
    current.current = next;
    set(next);
    if (hydratedFor.current) {
      // Agrupa alterações rápidas (ex.: digitação do ativo) em um único salvamento.
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => prefs.save({ [PREF_KEY]: serializeFilters(next) }), 500);
    }
  };
  const reset = () => setFilters(DEFAULT_FILTERS);

  // Evita buscar dados com o filtro padrão antes de carregar o filtro salvo.
  if (user && hydratedFor.current !== user.id && !prefs.loaded && !prefs.failed) return <Loading />;
  return <Ctx.Provider value={{ filters, setFilters, reset }}>{children}</Ctx.Provider>;
}

export function useFilters() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useFilters fora do provider");
  return v;
}

/** Converte os filtros globais em parâmetros da API. */
export function useFilterParams() {
  const { filters } = useFilters();
  return useMemo(() => toParams(filters), [filters]);
}

export function toParams(f: GlobalFilters, now = new Date()): Record<string, unknown> {
  let start: Date | null = null;
  let end: Date | null = null;
  const days = { "7d": 7, "30d": 30, "90d": 90, "1y": 365 } as Record<string, number>;
  if (f.period in days) start = new Date(now.getTime() - days[f.period] * 86400_000);
  if (f.period === "month") start = new Date(now.getFullYear(), now.getMonth(), 1);
  if (f.period === "prevmonth") {
    start = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    end = new Date(new Date(now.getFullYear(), now.getMonth(), 1).getTime() - 1000);
  }
  if (f.period === "ytd") start = new Date(now.getFullYear(), 0, 1);
  if (f.period === "custom") {
    start = f.range[0];
    end = f.range[1] ? new Date(f.range[1].getTime() + 86399_000) : null;
  }
  return {
    start: start?.toISOString(),
    end: end?.toISOString(),
    connection_id: f.connectionIds,
    asset: f.asset || undefined,
    side: f.side || undefined,
    market: f.market || undefined,
    provider: f.provider || undefined,
  };
}
