import { toParams, type GlobalFilters } from "../components/FiltersContext";
import { fmtMoney, fmtNumber, fmtPct, signColor } from "../lib/format";

describe("formatação", () => {
  it("formata valores em BRL e cripto", () => {
    expect(fmtMoney("1234.5", "BRL")).toBe("1.234,50 BRL");
    expect(fmtMoney(null, "USDT")).toBe("—");
    expect(fmtNumber("0.00012345")).toBe("0,00012345");
    expect(fmtPct(12.345)).toBe("12,35%");
  });
  it("cores por sinal", () => {
    expect(signColor("-1")).toBe("red");
    expect(signColor("2")).toBe("teal");
    expect(signColor(null)).toBeUndefined();
  });
});

describe("filtros globais", () => {
  const base: GlobalFilters = { period: "7d", range: [null, null], connectionIds: ["c1"], asset: "BTC", side: "SELL", market: "", provider: "" };
  it("converte período relativo em data inicial", () => {
    const now = new Date("2026-01-10T00:00:00Z");
    const p = toParams(base, now);
    expect(p.start).toBe("2026-01-03T00:00:00.000Z");
    expect(p.end).toBeUndefined();
    expect(p.connection_id).toEqual(["c1"]);
    expect(p.side).toBe("SELL");
  });
  it("período personalizado inclui o dia final inteiro", () => {
    const p = toParams({ ...base, period: "custom", range: [new Date("2026-01-01T00:00:00Z"), new Date("2026-01-02T00:00:00Z")] });
    expect(p.end).toBe("2026-01-02T23:59:59.000Z");
  });
});

describe("filtros salvos no perfil", () => {
  it("serializa datas sem fuso e restaura", async () => {
    const { serializeFilters, deserializeFilters } = await import("../components/FiltersContext");
    const f: GlobalFilters = { period: "custom", range: [new Date(2026, 0, 5), new Date(2026, 0, 20)], connectionIds: ["c1"], asset: "BTC", side: "", market: "", provider: "" };
    const saved = serializeFilters(f);
    expect(saved.range).toEqual(["2026-01-05", "2026-01-20"]);
    const back = deserializeFilters(JSON.parse(JSON.stringify(saved)));
    expect(back.range[0]?.getDate()).toBe(5);
    expect(back.connectionIds).toEqual(["c1"]);
    expect(back.asset).toBe("BTC");
  });
  it("ignora valores inválidos vindos do servidor", async () => {
    const { deserializeFilters, DEFAULT_FILTERS } = await import("../components/FiltersContext");
    expect(deserializeFilters(null)).toEqual(DEFAULT_FILTERS);
    const v = deserializeFilters({ period: "xyz", side: "HACK", connectionIds: [1, "ok"], range: ["nada", null] });
    expect(v.period).toBe(DEFAULT_FILTERS.period);
    expect(v.side).toBe("");
    expect(v.connectionIds).toEqual(["ok"]);
    expect(v.range).toEqual([null, null]);
  });
});
