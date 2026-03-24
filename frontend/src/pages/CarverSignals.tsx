import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { RefreshCw, TrendingUp, TrendingDown, Minus, ArrowUpDown, AlertTriangle } from 'lucide-react'
import { fetchCarverSignals } from '../api/client'
import type { CarverStock } from '../types'
import { fmtPct, fmtNum } from '../utils/format'

type SortKey = 'momentum_rank' | 'combined_forecast' | 'momentum_return' | 'close' | 'position_value'

const SIGNAL_COLORS: Record<string, string> = {
  BUY: 'text-success bg-success/15 border-success/30',
  HOLD: 'text-primary bg-primary/15 border-primary/30',
  REDUCE: 'text-danger bg-danger/15 border-danger/30',
  NEUTRAL: 'text-gray-400 bg-gray-500/10 border-gray-600/30',
  NO_DATA: 'text-gray-600 bg-gray-800/50 border-gray-700/30',
}

export default function CarverSignals() {
  const [capital, setCapital] = useState(500_000_000)
  const [activeCapital, setActiveCapital] = useState(500_000_000)
  const [sortKey, setSortKey] = useState<SortKey>('momentum_rank')
  const [sortAsc, setSortAsc] = useState(true)
  const [filter, setFilter] = useState<string>('all')

  const { data, isLoading, isRefetching, refetch } = useQuery({
    queryKey: ['carver-signals', activeCapital],
    queryFn: () => fetchCarverSignals(30, activeCapital),
    staleTime: 60_000,
  })

  const capitalChanged = capital !== activeCapital

  if (isLoading) {
    return (
      <div className="flex items-center gap-3 text-gray-400 mt-12 justify-center">
        <RefreshCw size={18} className="animate-spin" /> Loading Carver signals...
      </div>
    )
  }

  if (!data?.available) {
    return (
      <div className="card text-center py-12">
        <AlertTriangle size={32} className="text-warning mx-auto mb-3" />
        <p className="text-gray-300">Failed to load signals</p>
        <p className="text-sm text-gray-500 mt-1">{data?.error ?? 'Unknown error'}</p>
        <button className="btn-primary mt-4" onClick={() => refetch()}>Retry</button>
      </div>
    )
  }

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc)
    else { setSortKey(key); setSortAsc(key === 'momentum_rank') }
  }

  const stocks = [...(data.stocks ?? [])]
    .filter(s => {
      if (filter === 'all') return true
      return s.signal === filter
    })
    .sort((a, b) => {
      const av = a[sortKey] ?? 999
      const bv = b[sortKey] ?? 999
      return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number)
    })

  const { summary } = data

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Carver Strategy Signals</h1>
          <p className="text-sm text-gray-500 mt-1">
            Momentum + IBS combined forecasts &middot; {data.scan_date ?? '—'}
          </p>
        </div>
        <button
          className="btn-primary text-sm flex items-center gap-2"
          onClick={() => refetch()}
          disabled={isRefetching}
        >
          <RefreshCw size={14} className={isRefetching ? 'animate-spin' : ''} />
          {isRefetching ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {/* Regime + Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <div className={`card p-3 border ${data.regime === 'BULL' ? 'border-success/30 bg-success/5' : 'border-danger/30 bg-danger/5'}`}>
          <p className="text-xs text-gray-500">Regime</p>
          <p className={`text-lg font-bold ${data.regime === 'BULL' ? 'text-success' : 'text-danger'}`}>
            {data.regime === 'BULL' ? '🐂' : '🐻'} {data.regime}
          </p>
          <p className="text-xs text-gray-500">Tau: {data.tau_multiplier}x</p>
        </div>

        <div className="card p-3">
          <p className="text-xs text-gray-500">BUY Signals</p>
          <p className="text-lg font-bold text-success">{summary.buy}</p>
          <p className="text-xs text-gray-500">forecast &gt; 5</p>
        </div>
        <div className="card p-3">
          <p className="text-xs text-gray-500">HOLD</p>
          <p className="text-lg font-bold text-primary">{summary.hold}</p>
          <p className="text-xs text-gray-500">forecast 0–5</p>
        </div>
        <div className="card p-3">
          <p className="text-xs text-gray-500">REDUCE</p>
          <p className="text-lg font-bold text-danger">{summary.reduce}</p>
          <p className="text-xs text-gray-500">forecast &lt; -3</p>
        </div>
        <div className="card p-3">
          <p className="text-xs text-gray-500">Exposure</p>
          <p className="text-lg font-bold text-gray-200">{data.exposure_pct}%</p>
          <p className="text-xs text-gray-500">{(data.total_exposure / 1e6).toFixed(0)}M VND</p>
        </div>
        <div className="card p-3">
          <p className="text-xs text-gray-500">Capital</p>
          <div className="flex gap-1.5 mt-1">
            <input
              type="number"
              className="input text-sm w-full"
              value={capital}
              min={100_000_000} max={10_000_000_000} step={50_000_000}
              onChange={e => setCapital(+e.target.value)}
            />
            <button
              className={`px-2.5 py-1 text-xs font-medium rounded-lg border transition-colors whitespace-nowrap ${
                capitalChanged
                  ? 'border-primary bg-primary/15 text-primary hover:bg-primary/25'
                  : 'border-border text-gray-600 cursor-default'
              }`}
              disabled={!capitalChanged || isRefetching}
              onClick={() => setActiveCapital(capital)}
            >
              Load
            </button>
          </div>
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-2">
        {['all', 'BUY', 'HOLD', 'REDUCE', 'NEUTRAL'].map(f => (
          <button
            key={f}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
              filter === f
                ? 'border-primary bg-primary/15 text-primary'
                : 'border-border text-gray-400 hover:text-gray-200 hover:border-gray-600'
            }`}
            onClick={() => setFilter(f)}
          >
            {f === 'all' ? `All (${data.stocks.length})` : `${f} (${summary[f.toLowerCase() as keyof typeof summary] ?? 0})`}
          </button>
        ))}
      </div>

      {/* Stock table */}
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 border-b border-border">
              <th className="py-2 px-3 cursor-pointer hover:text-gray-300" onClick={() => handleSort('momentum_rank')}>
                <span className="flex items-center gap-1">Rank <ArrowUpDown size={10} /></span>
              </th>
              <th className="py-2 px-3">Ticker</th>
              <th className="py-2 px-3 cursor-pointer hover:text-gray-300" onClick={() => handleSort('close')}>
                <span className="flex items-center gap-1">Close <ArrowUpDown size={10} /></span>
              </th>
              <th className="py-2 px-3 cursor-pointer hover:text-gray-300" onClick={() => handleSort('momentum_return')}>
                <span className="flex items-center gap-1">3M Return <ArrowUpDown size={10} /></span>
              </th>
              <th className="py-2 px-3">Mom Fcst</th>
              <th className="py-2 px-3">IBS Fcst</th>
              <th className="py-2 px-3 cursor-pointer hover:text-gray-300" onClick={() => handleSort('combined_forecast')}>
                <span className="flex items-center gap-1">Combined <ArrowUpDown size={10} /></span>
              </th>
              <th className="py-2 px-3">Signal</th>
              <th className="py-2 px-3">Vol</th>
              <th className="py-2 px-3 cursor-pointer hover:text-gray-300" onClick={() => handleSort('position_value')}>
                <span className="flex items-center gap-1">Position <ArrowUpDown size={10} /></span>
              </th>
              <th className="py-2 px-3">Shares</th>
            </tr>
          </thead>
          <tbody>
            {stocks.map((s: CarverStock) => (
              <StockRow key={s.ticker} stock={s} />
            ))}
          </tbody>
        </table>
        {stocks.length === 0 && (
          <p className="text-center text-gray-500 py-6">No stocks match the current filter.</p>
        )}
      </div>

      {/* How to use */}
      <div className="card space-y-3">
        <h2 className="text-sm font-semibold text-gray-300">How to use Carver signals</h2>
        <div className="text-xs text-gray-500 space-y-2">
          <p><strong className="text-gray-400">1. Check regime</strong> — In BEAR, positions are halved and no new entries. Wait for BULL.</p>
          <p><strong className="text-gray-400">2. BUY signals (forecast &gt; 5)</strong> — Top momentum stocks. Buy the recommended shares at market open.</p>
          <p><strong className="text-gray-400">3. HOLD (0–5)</strong> — Modest positive forecast. Keep existing positions, don't add.</p>
          <p><strong className="text-gray-400">4. REDUCE (forecast &lt; -3)</strong> — Bottom momentum. Trim or exit these positions.</p>
          <p><strong className="text-gray-400">5. Rebalance monthly</strong> — Momentum signal updates every ~21 trading days. IBS updates daily.</p>
          <p><strong className="text-gray-400">6. Position sizing</strong> — Shares column shows Carver-optimal lot-rounded position. Respect the buffer zone (don't trade if within 20% of optimal).</p>
        </div>
      </div>
    </div>
  )
}

function StockRow({ stock: s }: { stock: CarverStock }) {
  const fcstBar = Math.min(Math.abs(s.combined_forecast) / 20 * 100, 100)
  const fcstPositive = s.combined_forecast >= 0

  return (
    <tr className="border-b border-border/50 hover:bg-white/[0.02] transition-colors">
      <td className="py-2.5 px-3 text-gray-400 font-mono text-xs">
        {s.momentum_rank ?? '—'}
      </td>
      <td className="py-2.5 px-3 font-medium text-gray-200">
        {s.ticker.replace('.VN', '')}
      </td>
      <td className="py-2.5 px-3 text-gray-300 font-mono text-xs">
        {s.close != null ? s.close.toLocaleString() : '—'}
      </td>
      <td className="py-2.5 px-3">
        {s.momentum_return != null ? (
          <span className={`flex items-center gap-1 text-xs font-medium ${
            s.momentum_return > 0 ? 'text-success' : s.momentum_return < 0 ? 'text-danger' : 'text-gray-400'
          }`}>
            {s.momentum_return > 0 ? <TrendingUp size={12} /> : s.momentum_return < 0 ? <TrendingDown size={12} /> : <Minus size={12} />}
            {fmtPct(s.momentum_return)}
          </span>
        ) : <span className="text-gray-600 text-xs">—</span>}
      </td>
      <td className="py-2.5 px-3">
        <ForecastBadge value={s.cm_forecast} />
      </td>
      <td className="py-2.5 px-3">
        <ForecastBadge value={s.ibs_forecast} />
      </td>
      <td className="py-2.5 px-3">
        <div className="flex items-center gap-2">
          <span className={`text-xs font-bold w-8 text-right ${
            s.combined_forecast > 5 ? 'text-success' :
            s.combined_forecast > 0 ? 'text-primary' :
            s.combined_forecast < -3 ? 'text-danger' : 'text-gray-400'
          }`}>
            {s.combined_forecast > 0 ? '+' : ''}{s.combined_forecast.toFixed(1)}
          </span>
          <div className="w-16 h-1.5 bg-gray-800 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${fcstPositive ? 'bg-success' : 'bg-danger'}`}
              style={{ width: `${fcstBar}%` }}
            />
          </div>
        </div>
      </td>
      <td className="py-2.5 px-3">
        <span className={`text-xs font-medium px-2 py-0.5 rounded border ${SIGNAL_COLORS[s.signal]}`}>
          {s.signal}
        </span>
      </td>
      <td className="py-2.5 px-3 text-xs text-gray-400 font-mono">
        {s.annual_vol != null ? fmtPct(s.annual_vol) : '—'}
      </td>
      <td className="py-2.5 px-3 text-xs text-gray-300 font-mono">
        {s.position_value > 0 ? `${(s.position_value / 1e6).toFixed(1)}M` : '—'}
      </td>
      <td className="py-2.5 px-3 text-xs text-gray-300 font-mono">
        {s.optimal_shares > 0 ? s.optimal_shares.toLocaleString() : '—'}
      </td>
    </tr>
  )
}

function ForecastBadge({ value }: { value: number }) {
  if (value === 0) return <span className="text-xs text-gray-600">0</span>
  return (
    <span className={`text-xs font-mono ${
      value > 0 ? 'text-success' : 'text-danger'
    }`}>
      {value > 0 ? '+' : ''}{value.toFixed(1)}
    </span>
  )
}
