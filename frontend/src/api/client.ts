import axios from 'axios'
import type {
  BacktestRun,
  ConfigData,
  EquityPoint,
  Job,
  Metrics,
  PermutationData,
  PortfolioData,
  RegimeData,
  ScannerData,
  Trade,
} from '../types'

const api = axios.create({ baseURL: '/api' })

// ─── History ──────────────────────────────────────────────────────────────────
export async function fetchHistory(): Promise<{ runs: BacktestRun[]; count: number }> {
  const { data } = await api.get('/history')
  return data
}

export async function deleteRun(runId: string): Promise<void> {
  await api.delete(`/history/${runId}`)
}

export async function clearAllHistory(): Promise<void> {
  await api.delete('/history')
}

// ─── Per-run data ─────────────────────────────────────────────────────────────
export async function fetchEquity(runId: string): Promise<EquityPoint[]> {
  const { data } = await api.get(`/equity/${runId}`)
  return data
}

export async function fetchTrades(runId: string): Promise<Trade[]> {
  const { data } = await api.get(`/trades/${runId}`)
  return data
}

export async function fetchMetrics(runId: string): Promise<Metrics> {
  const { data } = await api.get(`/metrics/${runId}`)
  return data
}

// ─── Regime ───────────────────────────────────────────────────────────────────
export async function fetchRegime(): Promise<RegimeData> {
  const { data } = await api.get('/regime')
  return data
}

// ─── Permutation ──────────────────────────────────────────────────────────────
export async function fetchPermutation(): Promise<PermutationData> {
  const { data } = await api.get('/permutation')
  return data
}

// ─── Config ───────────────────────────────────────────────────────────────────
export async function fetchConfig(): Promise<ConfigData> {
  const { data } = await api.get('/config')
  return data
}

export async function saveConfig(overrides: Record<string, number | boolean>): Promise<void> {
  await api.post('/config', overrides)
}

export async function clearConfigOverrides(): Promise<void> {
  await api.delete('/config/overrides')
}

// ─── Portfolio ────────────────────────────────────────────────────────────────
export async function fetchPortfolio(): Promise<PortfolioData> {
  const { data } = await api.get('/portfolio')
  return data
}

export interface TradeRecordParams {
  ticker: string
  action: 'BUY' | 'SELL'
  shares: number
  price: number
  stop_price?: number
  r_value?: number
  pattern?: string
  strategy?: string
  note?: string
}

export async function recordTrade(params: TradeRecordParams): Promise<{ recorded: boolean }> {
  const { data } = await api.post('/portfolio/trade', params)
  return data
}

export async function deleteTrade(index: number): Promise<void> {
  await api.delete(`/portfolio/trade/${index}`)
}

export async function deleteHolding(ticker: string): Promise<void> {
  await api.delete(`/portfolio/holding/${encodeURIComponent(ticker)}`)
}

// ─── Scanner ─────────────────────────────────────────────────────────────────
export async function fetchScanner(nStocks = 30, equity = 500_000_000): Promise<ScannerData> {
  const { data } = await api.get('/scanner', { params: { n_stocks: nStocks, equity } })
  return data
}

// ─── Universe ─────────────────────────────────────────────────────────────────
export async function fetchUniverse(): Promise<string[]> {
  const { data } = await api.get('/universe')
  return data.tickers
}

// ─── Job management ───────────────────────────────────────────────────────────
export interface BacktestParams {
  n_stocks: number
  years: number
  capital: number
  use_real: boolean
  strategy?: 'carver' | 'martin_luk'
  config_overrides?: Record<string, number | boolean>
}

export interface PermutationParams {
  n_perm: number
  years: number
  n_stocks: number
  use_real: boolean
  metric: string
  strategy?: 'carver' | 'martin_luk'
}

export async function startBacktest(params: BacktestParams): Promise<string> {
  const { data } = await api.post('/run-backtest', params)
  return data.job_id
}

export async function startPermutation(params: PermutationParams): Promise<string> {
  const { data } = await api.post('/run-permutation', params)
  return data.job_id
}

export async function fetchJob(jobId: string): Promise<Job> {
  const { data } = await api.get(`/job/${jobId}`)
  return data
}
