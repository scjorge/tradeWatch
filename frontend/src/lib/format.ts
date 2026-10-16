import type { Dec } from "../api/types";

const FIAT = new Set(["BRL", "USD", "EUR", "USDT", "USDC", "FDUSD"]);

/** Formata um decimal (string) para exibição. Apenas apresentação: cálculos ficam no backend. */
export function fmtNumber(v: Dec | number | undefined, maxDigits = 8): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (Number.isNaN(n)) return "—";
  if (!Number.isFinite(n)) return String(v);
  const abs = Math.abs(n);
  const digits = abs >= 1000 ? 2 : abs >= 1 ? Math.min(4, maxDigits) : maxDigits;
  return n.toLocaleString("pt-BR", { maximumFractionDigits: digits });
}

export function fmtMoney(v: Dec | number | undefined, currency: string): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (Number.isNaN(n)) return "—";
  if (!Number.isFinite(n)) return String(v);
  const digits = FIAT.has(currency) ? 2 : 8;
  return `${n.toLocaleString("pt-BR", { minimumFractionDigits: FIAT.has(currency) ? 2 : 0, maximumFractionDigits: digits })} ${currency}`;
}

export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${v.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}%`;
}

export function fmtDate(iso: string | null | undefined, tz?: string, withTime = true): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("pt-BR", {
    timeZone: tz,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

export function relative(iso: string | null | undefined): string {
  if (!iso) return "nunca";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "agora há pouco";
  if (diff < 3600) return `há ${Math.round(diff / 60)} min`;
  if (diff < 86400) return `há ${Math.round(diff / 3600)} h`;
  return `há ${Math.round(diff / 86400)} dia(s)`;
}

export function signColor(v: Dec | number | undefined): string | undefined {
  if (v === null || v === undefined) return undefined;
  const n = Number(v);
  if (n > 0) return "teal";
  if (n < 0) return "red";
  return undefined;
}
