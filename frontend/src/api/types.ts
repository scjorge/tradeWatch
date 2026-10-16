// Valores financeiros chegam como string decimal para preservar precisão.
export type Dec = string | null;

export interface User {
  id: string;
  email: string;
  display_name: string;
  email_verified: boolean;
  roles: string[];
  permissions: string[];
  timezone: string;
  base_currency: string;
  cost_method: "FIFO" | "AVERAGE";
  mfa_enabled: boolean;
  created_at: string;
}

export interface NavItem {
  label: string;
  path: string;
  icon: string;
  order: number;
}

export interface ModuleInfo {
  key: string;
  name: string;
  user_enabled: boolean;
  nav: NavItem[];
}

export interface CredentialField {
  name: string;
  label: string;
  secret: boolean;
  help: string;
}

export interface Provider {
  key: string;
  name: string;
  docs_url: string;
  instructions: string[];
  credential_fields: CredentialField[];
  capabilities: { rate_limit: string; notes: string[]; deposits: boolean; withdrawals: boolean };
}

export type ConnectionStatus = "pending_validation" | "active" | "syncing" | "error" | "invalid_credentials" | "suspended";

export interface Connection {
  id: string;
  name: string;
  provider: string;
  provider_name: string;
  status: ConnectionStatus;
  status_message: string | null;
  settings: { extra_symbols?: string[]; history_start?: string };
  credential_hint: string | null;
  credential_updated_at: string | null;
  last_sync_at: string | null;
  last_successful_sync_at: string | null;
  last_error_at: string | null;
  consecutive_failures: number;
  created_at: string;
  current_job: { id: string; status: string; run_after: string } | null;
}

export interface SyncJob {
  id: string;
  kind: string;
  trigger: string;
  status: string;
  attempts: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  run_after: string;
  error_message: string | null;
  stats: Record<string, number | string>;
}

export interface Execution {
  id: string;
  executed_at: string;
  provider: string;
  connection_id: string;
  connection_name: string;
  market: string;
  symbol: string;
  base_asset: string;
  quote_asset: string;
  side: "BUY" | "SELL";
  quantity: string;
  price: string;
  gross_value: string;
  fee: string;
  fee_asset: string | null;
  fee_value: Dec;
  fee_value_currency: string | null;
  net_value: Dec;
  external_id: string | null;
  external_order_id: string | null;
  order_id: string | null;
  source: string;
  sync_status: string;
}

export interface Paged<T> {
  total: number;
  items: T[];
}

export interface HoldingRow {
  connection_id: string;
  connection_name: string;
  provider: string;
  asset: string;
  free: string;
  locked: string;
  total: string;
  reported_at: string;
  price: Dec;
  price_source: string | null;
  price_at: string | null;
  value: Dec;
}

export interface Holdings {
  base_currency: string;
  total_value: Dec;
  complete: boolean;
  unpriced_assets: string[];
  rows: HoldingRow[];
  by_asset: { asset: string; quantity: string; value: Dec; share_pct: number | null; priced: boolean }[];
  by_connection: { connection_id: string; name: string; provider: string; value: Dec }[];
}

export interface RealizedSummary {
  base_currency: string;
  method: string;
  realized_net: Dec;
  realized_gross: Dec;
  fees_paid: Dec;
  fees_complete: boolean;
  realized_return_pct: number | null;
  records_total: number;
  records_incomplete: number;
  executions_count: number;
  closed_operations: number;
  win_rate_pct: number | null;
  avg_gain: Dec;
  avg_loss: Dec;
  best: { asset: string; realized_pnl: Dec; realized_at: string } | null;
  worst: { asset: string; realized_pnl: Dec; realized_at: string } | null;
}

export interface PeriodPnl {
  period: string;
  realized: string;
  fees: string;
  incomplete: number;
  operations: number;
}

export interface EquityPoint {
  date: string;
  value: Dec;
  complete: boolean;
}

export interface Dashboard {
  base_currency: string;
  method: string;
  holdings: Holdings;
  realized: RealizedSummary;
  unrealized: { total: Dec; complete: boolean; open_cost_basis: Dec };
  equity_history: EquityPoint[];
  pnl_by_period: PeriodPnl[];
  recent_activity: { id: string; executed_at: string; connection_name: string; symbol: string; side: string; quantity: string; price: string; quote_quantity: string; quote_asset: string }[];
  integrations: { id: string; name: string; provider: string; status: ConnectionStatus; status_message: string | null; last_successful_sync_at: string | null; last_job_status: string | null }[];
  last_sync_at: string | null;
}

export interface PositionRow {
  asset: string;
  quantity: string;
  reported_quantity: Dec;
  difference: Dec;
  cost_basis: Dec;
  avg_cost: Dec;
  cost_basis_complete: boolean;
  unknown_cost_quantity: string;
  price: Dec;
  price_source: string | null;
  price_at: string | null;
  market_value: Dec;
  unrealized_pnl: Dec;
  unrealized_pct: number | null;
  method: string;
  computed_at: string;
}

export interface RealizedRecord {
  id: string;
  kind: "sale" | "conversion" | "fee";
  asset: string;
  quantity: string;
  proceeds: Dec;
  cost_basis: Dec;
  fees: Dec;
  realized_pnl: Dec;
  status: "complete" | "incomplete";
  note: string | null;
  method: string;
  base_currency: string;
  realized_at: string;
  execution_id: string | null;
}

export interface Channel {
  id: string;
  kind: string;
  name: string;
  status: string;
  enabled: boolean;
  bot_username: string | null;
  chat_title: string | null;
  chat_type: string | null;
  verified_at: string | null;
  last_error: string | null;
  token_hint: string | null;
  created_at: string;
}

export interface VerificationPayload {
  channel: Channel;
  verification_code: string;
  expires_in_minutes: number;
  instructions: string[];
}

export interface Preference {
  event_type: string;
  label: string;
  enabled: boolean;
  settings: Record<string, number>;
}


// ---------------------------------------------------------------- operações compra → venda
export type CycleStatus = "buy_order" | "open" | "sell_order" | "closed";

export interface CycleRow {
  id: string;
  status: CycleStatus;
  status_label: string;
  asset: string;
  quote: string | null;
  sell_quote: string | null;
  complete: boolean;
  note: string | null;
  source: string | null;
  account: string | null;
  buy_at: string | null;
  buy_quantity: Dec;
  buy_price: Dec;
  buy_fee: Dec;
  buy_fee_asset: string | null;
  buy_unit_brl: Dec;
  buy_total: Dec;
  buy_fx: Dec;
  buy_total_brl: Dec;
  sell_at: string | null;
  sell_quantity: Dec;
  sell_price: Dec;
  sell_fee: Dec;
  sell_fee_asset: string | null;
  sell_unit_brl: Dec;
  sell_total: Dec;
  sell_fx: Dec;
  sell_total_brl: Dec;
  pnl_brl: Dec;
  pnl_pct: number | null;
  pnl_quote: Dec;
  fx_effect_brl: Dec;
  fees_brl: Dec;
  holding_days: number | null;
  estimated: boolean;
  price_source: string | null;
  /** Somente na versão consolidada. */
  parts?: number;
  buy_executions?: number;
  sell_executions?: number;
}

export interface CyclePeriod {
  period: string;
  pnl_brl: string;
  gains_brl: string;
  losses_brl: string;
  cumulative_brl: string;
  count: number;
  win_rate_pct: number | null;
  return_pct: number | null;
  invested_brl: string;
  fees_brl: string;
  change_vs_prev_brl: Dec;
}

export interface CycleSummary {
  granularity: string;
  closed_count: number;
  wins: number;
  losses: number;
  win_rate_pct: number | null;
  pnl_brl: string;
  gains_brl: string;
  losses_brl: string;
  invested_closed_brl: string;
  return_pct: number | null;
  fees_brl: string;
  fx_effect_brl: string;
  avg_gain_brl: Dec;
  avg_loss_brl: Dec;
  payoff_ratio: number | null;
  profit_factor: number | null;
  avg_holding_days: number | null;
  best: { id: string; asset: string; pnl_brl: Dec; pnl_pct: number | null } | null;
  worst: { id: string; asset: string; pnl_brl: Dec; pnl_pct: number | null } | null;
  incomplete_count: number;
  open_count: number;
  open_invested_brl: string;
  unrealized_brl: string;
  unrealized_complete: boolean;
  pending_orders: number;
  periods: CyclePeriod[];
  by_asset: { asset: string; pnl_brl: string; count: number; win_rate_pct: number; return_pct: number | null }[];
}
