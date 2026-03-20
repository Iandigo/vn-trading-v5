export interface BacktestRun {
  run_id: string
  timestamp: string
  params: {
    n_stocks: number
    years: number
    capital: number
    data_source: 'real' | 'mock'
  }
  metrics: Metrics
  equity_file?: string
  trades_file?: string
}

export interface Metrics {
  cagr: number
  sharpe: number
  sortino: number
  calmar: number
  max_drawdown: number
  annual_vol: number
  win_rate: number
  total_return: number
  n_years: number
  avg_monthly_return: number
  start_date: string
  end_date: string
  cost_drag_annual: number
  total_fees_vnd: number
  n_trades: number
  trades_per_month: number
  regime_pct_bull: number
}

export interface EquityPoint {
  date: string
  equity: number
  cash: number
  positions_value: number
  regime?: string
  drawdown: number
}

export interface Trade {
  date: string
  ticker: string
  action: 'BUY' | 'SELL'
  shares: number
  price: number
  value: number
  fee: number
  regime?: string
  forecast?: number
}

export interface RegimeData {
  available: boolean
  regime: string
  ma200: number | null
  index_close: number | null
  pct_vs_ma200: number | null
  days_in_regime: number
  tau_multiplier: number
  allow_new_entries: boolean
  effective_tau: number
  target_vol: number
  signal_weights: { cross_momentum: number; ibs: number }
  chart_data: Array<{ date: string; vnindex: number; ma200: number | null }>
  error?: string
}

export interface PermutationData {
  available: boolean
  metric: string
  real_value: number
  p_value: number
  p_ci_low: number
  p_ci_high: number
  n_permutations: number
  perm_mean: number
  perm_median: number
  n_beats_real: number
  verdict: string
  years: number
  n_stocks: number
  perm_distribution: number[]
}

export interface ConfigData {
  MA_REGIME: Record<string, number | boolean>
  CROSS_MOMENTUM: Record<string, number>
  IBS: Record<string, number | boolean>
  SIGNAL_WEIGHTS: { cross_momentum: number; ibs: number }
  FDM: number
  FORECAST_CAP: number
  SIZING: Record<string, number>
  COSTS: Record<string, number>
  BACKTEST: Record<string, number>
  UNIVERSE: string[]
  overrides: Record<string, number | boolean>
  has_overrides: boolean
}

export interface PortfolioData {
  available: boolean
  holdings: Record<string, number>
  open_positions: number
  trades: Trade[]
}

export interface Job {
  status: 'running' | 'completed' | 'failed'
  stage: string
  progress: number
  result: { metrics: Metrics } | null
  error: string | null
}

export type Page =
  | 'results'
  | 'trades'
  | 'history'
  | 'permutation'
  | 'regime'
  | 'portfolio'
  | 'config'
  | 'run'
