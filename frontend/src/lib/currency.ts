import { useAuth } from "../auth/AuthContext";

/** Moedas que o usuário pode escolher como padrão da plataforma (Configurações). */
export const CURRENCY_OPTIONS = [
  { value: "BRL", label: "Real (BRL)" },
  { value: "USDT", label: "Dólar (USDT)" },
];

export const DEFAULT_CURRENCY = "BRL";

/** Moeda padrão escolhida pelo usuário, em que resultados e patrimônio são exibidos. */
export function useCurrency(): string {
  const { user } = useAuth();
  return user?.base_currency ?? DEFAULT_CURRENCY;
}
