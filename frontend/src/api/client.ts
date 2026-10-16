// Cliente HTTP da API interna. Sessão via cookie HttpOnly; o token CSRF é lido
// do cookie "tw_csrf" e ecoado no cabeçalho em toda requisição que altera estado.

export class ApiError extends Error {
  status: number;
  code: string;
  details?: { field: string; message: string }[];
  constructor(status: number, code: string, message: string, details?: { field: string; message: string }[]) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function csrfToken(): string | undefined {
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith("tw_csrf="))
    ?.split("=")[1];
}

type Options = { method?: string; body?: unknown; form?: FormData; signal?: AbortSignal };

const listeners = new Set<() => void>();
export function onUnauthorized(fn: () => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export async function api<T = unknown>(path: string, opts: Options = {}): Promise<T> {
  const method = opts.method ?? (opts.body || opts.form ? "POST" : "GET");
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") {
    const t = csrfToken();
    if (t) headers["X-CSRF-Token"] = decodeURIComponent(t);
  }
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, { method, headers, body, credentials: "same-origin", signal: opts.signal });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = data?.error ?? {};
    if (res.status === 401 && !path.startsWith("/api/auth/login")) listeners.forEach((l) => l());
    const detail = err.details?.map((d: { field: string; message: string }) => `${d.field}: ${d.message}`).join("; ");
    throw new ApiError(res.status, err.code ?? "error", detail ? `${err.message} ${detail}` : err.message ?? `Erro ${res.status}`, err.details);
  }
  return data as T;
}

export function qs(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)));
    else sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}
