export type Strategy = 'carver' | 'martin_luk'

export interface BacktestRun {
  run_id: string
  timestamp: string
  params: {
    n_stocks: number
    years: number
    capital: number
    data_source: 'real' | 'mock'
    strategy?: Strategy
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
  // Martin Luk swing-specific metrics (optional)
  strategy?: string
  avg_winner_r?: number
  avg_loser_r?: number
  expectancy?: number
  max_consecutive_losses?: number
  avg_holding_days?: number
  partial_exit_count?: number
  health_pct_strong?: number
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
  // Martin Luk swing-specific fields
  reason?: string
  stop_price?: number
  r_value?: number
  r_multiple?: number
  health?: string
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
  holdings: Record<string, PortfolioHolding | number>
  open_positions: number
  trades: Array<Trade & { strategy?: string; stop_price?: number; r_value?: number; pattern?: string; note?: string }>
}

export interface Job {
  status: 'running' | 'completed' | 'failed'
  stage: string
  progress: number
  result: { metrics: Metrics } | null
  error: string | null
}

export interface ScannerStock {
  ticker: string
  classification: 'LEAD' | 'WEAKENING' | 'LAGGARD' | 'NO_DATA'
  adr: number | null
  ema_9: number | null
  ema_21: number | null
  ema_50: number | null
  close: number | null
  breakout: {
    pattern: string
    entry_price: number
    stop_price: number
    r_value: number
    target_3r: number
    target_5r: number
    shares: number
    position_value: number
    risk_amount: number
  } | null
}

export interface ScannerData {
  available: boolean
  scan_date: string | null
  stocks: ScannerStock[]
  market_health: {
    health: string
    leader_count: number
    total_stocks: number
    leader_pct: number
    risk_multiplier: number
  }
  summary: {
    lead: number
    weakening: number
    laggard: number
    signals: number
    total: number
  }
  equity: number
  error?: string
}

export interface PortfolioHolding {
  shares: number
  avg_price: number
  stop_price?: number
  r_value?: number
  pattern?: string
  strategy?: string
  entry_date?: string
}

export type Page =
  | 'results'
  | 'trades'
  | 'history'
  | 'permutation'
  | 'regime'
  | 'portfolio'
  | 'scanner'
  | 'config'
  | 'run'
