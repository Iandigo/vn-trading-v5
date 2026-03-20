import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fetchHistory, fetchEquity, fetchMetrics } from '../api/client'
import MetricCard from '../components/MetricCard'
import type { BacktestRun, Metrics } from '../types'

const fmtPct = (v: number | undefined, decimals = 1) =>
  v == null ? '—' : `${(v * 100).toFixed(decimals)}%`

const fmtNum = (v: number | undefined, decimals = 2) =>
  v == null ? '—' : v.toFixed(decimals)

const fmtVnd = (v: number | undefined) => {
  if (v == null) return '—'
  if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(1)}B`
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  return v.toLocaleString()
}

const SCORECARD: Array<{
  key: keyof Metrics
  label: string
  format: (v: number) => string
  pass: (v: number) => boolean
  target: string
}> = [
  { key: 'cagr',            label: 'CAGR',         format: v => fmtPct(v), pass: v => v >= 0.045, target: '> 4.5%' },
  { key: 'sharpe',          label: 'Sharpe Ratio',  format: v => fmtNum(v), pass: v => v >= 0.40,  target: '> 0.40' },
  { key: 'sortino',         label: 'Sortino',       format: v => fmtNum(v), pass: v => v >= 0.50,  target: '> 0.50' },
  { key: 'max_drawdown',    label: 'Max Drawdown',  format: v => fmtPct(v), pass: v => v > -0.30,  target: '> -30%' },
  { key: 'annual_vol',      label: 'Annual Vol',    format: v => fmtPct(v), pass: v => v >= 0.10 && v <= 0.25, target: '10–25%' },
  { key: 'win_rate',        label: 'Win Rate',      format: v => fmtPct(v), pass: v => v >= 0.45,  target: '> 45%' },
  { key: 'cost_drag_annual',label: 'Cost Drag/yr',  format: v => fmtPct(v), pass: v => v < 0.015,  target: '< 1.5%' },
]

export default function BacktestResults() {
  const { data: histData } = useQuery({ queryKey: ['history'], queryFn: fetchHistory })
  const runs: BacktestRun[] = histData?.runs ?? []

  const defaultRunId = runs.length > 0 ? runs[runs.length - 1].run_id : 'latest'
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)

  const runId = selectedRunId ?? defaultRunId

  const { data: metrics, isLoading: metricsLoading } = useQuery({
    queryKey: ['metrics', runId],
    queryFn: () => fetchMetrics(runId),
    enabled: !!runId,
  })

  const { data: equityData = [] } = useQuery({
    queryKey: ['equity', runId],
    queryFn: () => fetchEquity(runId),
    enabled: !!runId,
  })

  // Annual returns from equity curve
  const annualReturns = (() => {
    if (!equityData.length) return []
    const byYear: Record<string, number> = {}
    for (const pt of equityData) {
      const year = pt.date.slice(0, 4)
      byYear[year] = pt.equity
    }
    const years = Object.keys(byYear).sort()
    const result: { year: string; return: number }[] = []
    for (let i = 1; i < years.length; i++) {
      const prev = byYear[years[i - 1]]
      const curr = byYear[years[i]]
      if (prev && curr) result.push({ year: years[i], return: (curr / prev - 1) * 100 })
    }
    return result
  })()

  const selectedRun = runs.find(r => r.run_id === runId)
  const runLabel = (r: BacktestRun) =>
    `${r.timestamp}  —  ${r.params.n_stocks} stocks  ${r.params.years}y  [${r.params.data_source}]`

  if (!metrics && !metricsLoading && runs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4 text-gray-400">
        <p className="text-lg">No backtest results yet.</p>
        <p className="text-sm">Go to <span className="text-primary font-semibold">Run Backtest</span> to run your first backtest.</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-100">Backtest Results</h1>
      </div>

      {/* Run selector */}
      {runs.length > 0 && (
        <div className="card flex items-center gap-3">
          <label className="text-sm text-gray-400 whitespace-nowrap">Select run:</label>
          <select
            className="select text-sm flex-1"
            value={selectedRunId ?? defaultRunId}
            onChange={e => setSelectedRunId(e.target.value)}
          >
            {[...runs].reverse().map(r => (
              <option key={r.run_id} value={r.run_id}>{runLabel(r)}</option>
            ))}
          </select>
          {selectedRun && (
            <span className="text-xs text-gray-500 whitespace-nowrap">
              {selectedRun.params.n_stocks} stocks · {selectedRun.params.years}y · {selectedRun.params.data_source}
            </span>
          )}
        </div>
      )}

      {metricsLoading && (
        <div className="text-gray-400 text-sm">Loading metrics...</div>
      )}

      {metrics && (
        <>
          {/* Top metrics */}
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
            <MetricCard label="CAGR" value={fmtPct(metrics.cagr)}
              highlight={metrics.cagr >= 0.045 ? 'green' : 'red'} sub="target > 4.5%" />
            <MetricCard label="Sharpe" value={fmtNum(metrics.sharpe)}
              highlight={metrics.sharpe >= 0.40 ? 'green' : 'red'} sub="target > 0.40" />
            <MetricCard label="Sortino" value={fmtNum(metrics.sortino)}
              highlight={metrics.sortino >= 0.50 ? 'green' : 'red'} sub="target > 0.50" />
            <MetricCard label="Max Drawdown" value={fmtPct(metrics.max_drawdown)}
              highlight={metrics.max_drawdown > -0.30 ? 'green' : 'red'} sub="target > -30%" />
            <MetricCard label="Trades/month" value={String(metrics.trades_per_month ?? '—')}
              highlight={(metrics.trades_per_month ?? 99) < 30 ? 'green' : 'red'} sub="target < 30" />
            <MetricCard label="Cost Drag/yr" value={fmtPct(metrics.cost_drag_annual)}
              highlight={(metrics.cost_drag_annual ?? 1) < 0.015 ? 'green' : 'red'} sub="target < 1.5%" />
          </div>

          {/* Secondary metrics */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <MetricCard label="Total Return" value={fmtPct(metrics.total_return)} small />
            <MetricCard label="Annual Vol" value={fmtPct(metrics.annual_vol)} small />
            <MetricCard label="Total Fees" value={fmtVnd(metrics.total_fees_vnd)} small />
            <MetricCard label="% Bull Regime" value={fmtPct(metrics.regime_pct_bull)} small />
          </div>
        </>
      )}

      {/* Equity curve */}
      {equityData.length > 0 && (
        <div className="card">
          <h2 className="text-lg font-semibold mb-4 text-gray-200">Equity Curve</h2>
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={equityData} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
              <defs>
                <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#1B6CA8" stopOpacity={0.25} />
                  <stop offset="95%" stopColor="#1B6CA8" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
              <XAxis dataKey="date" tick={{ fill: '#718096', fontSize: 11 }}
                tickFormatter={d => d.slice(0, 7)} interval="preserveStartEnd" />
              <YAxis tick={{ fill: '#718096', fontSize: 11 }}
                tickFormatter={v => fmtVnd(v)} width={70} />
              <Tooltip
                contentStyle={{ background: '#1e2130', border: '1px solid #2d3748', borderRadius: 8 }}
                labelStyle={{ color: '#a0aec0' }}
                formatter={(v: number) => [fmtVnd(v), 'Portfolio Value']}
              />
              <Area type="monotone" dataKey="equity" stroke="#1B6CA8" strokeWidth={2}
                fill="url(#equityGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>

          <h2 className="text-lg font-semibold mt-6 mb-4 text-gray-200">Drawdown (%)</h2>
          <ResponsiveContainer width="100%" height={140}>
            <AreaChart data={equityData} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
              <defs>
                <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#E85D24" stopOpacity={0.30} />
                  <stop offset="95%" stopColor="#E85D24" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
              <XAxis dataKey="date" tick={{ fill: '#718096', fontSize: 11 }}
                tickFormatter={d => d.slice(0, 7)} interval="preserveStartEnd" />
              <YAxis tick={{ fill: '#718096', fontSize: 11 }}
                tickFormatter={v => `${v.toFixed(1)}%`} width={55} />
              <Tooltip
                contentStyle={{ background: '#1e2130', border: '1px solid #2d3748', borderRadius: 8 }}
                labelStyle={{ color: '#a0aec0' }}
                formatter={(v: number) => [`${v.toFixed(2)}%`, 'Drawdown']}
              />
              <Area type="monotone" dataKey="drawdown" stroke="#E85D24" strokeWidth={1.5}
                fill="url(#ddGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Carver scorecard */}
      {metrics && (
        <div className="card">
          <h2 className="text-lg font-semibold mb-4 text-gray-200">Carver Scorecard</h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 text-xs uppercase border-b border-border">
                <th className="text-left py-2 pr-4">Status</th>
                <th className="text-left py-2 pr-4">Metric</th>
                <th className="text-right py-2 pr-4">Value</th>
                <th className="text-right py-2">Target</th>
              </tr>
            </thead>
            <tbody>
              {SCORECARD.map(row => {
                const val = metrics[row.key] as number
                const passed = val != null && row.pass(val)
                return (
                  <tr key={row.key} className="border-b border-border/50 hover:bg-white/2">
                    <td className="py-2 pr-4">{passed ? '✅' : '❌'}</td>
                    <td className="py-2 pr-4 text-gray-300">{row.label}</td>
                    <td className={`py-2 pr-4 text-right font-mono font-semibold ${passed ? 'text-success' : 'text-danger'}`}>
                      {val != null ? row.format(val) : '—'}
                    </td>
                    <td className="py-2 text-right text-gray-500">{row.target}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Annual returns */}
      {annualReturns.length > 0 && (
        <div className="card">
          <h2 className="text-lg font-semibold mb-4 text-gray-200">Annual Returns</h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={annualReturns} margin={{ top: 16, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
              <XAxis dataKey="year" tick={{ fill: '#718096', fontSize: 12 }} />
              <YAxis tick={{ fill: '#718096', fontSize: 11 }}
                tickFormatter={v => `${v.toFixed(0)}%`} width={45} />
              <Tooltip
                contentStyle={{ background: '#1e2130', border: '1px solid #2d3748', borderRadius: 8 }}
                formatter={(v: number) => [`${v.toFixed(2)}%`, 'Return']}
              />
              <Bar dataKey="return" radius={[4, 4, 0, 0]} label={{ position: 'top', fill: '#718096', fontSize: 11,
                formatter: (v: number) => `${v > 0 ? '+' : ''}${v.toFixed(1)}%` }}>
                {annualReturns.map((entry, i) => (
                  <Cell key={i} fill={entry.return >= 0 ? '#1B6CA8' : '#E85D24'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
