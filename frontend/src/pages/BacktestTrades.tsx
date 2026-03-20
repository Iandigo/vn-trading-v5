import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fetchHistory, fetchTrades } from '../api/client'
import type { BacktestRun, Trade } from '../types'

const fmtVnd = (v: number) => {
  if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(1)}B`
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  return v.toLocaleString()
}

interface WinLossRow {
  ticker: string
  wins: number
  losses: number
  total: number
  winRate: number
  totalPnl: number
  avgPnl: number
  feesPaid: number
}

function computeWinLoss(trades: Trade[]): WinLossRow[] {
  const byTicker: Record<string, Trade[]> = {}
  for (const t of trades) {
    if (!byTicker[t.ticker]) byTicker[t.ticker] = []
    byTicker[t.ticker].push(t)
  }

  const rows: WinLossRow[] = []

  for (const [ticker, tickerTrades] of Object.entries(byTicker)) {
    const sorted = [...tickerTrades].sort((a, b) => a.date.localeCompare(b.date))
    const buyQueue: Array<{ shares: number; price: number; fee: number }> = []
    let wins = 0, losses = 0, totalPnl = 0, totalFees = 0

    for (const t of sorted) {
      if (t.action === 'BUY') {
        buyQueue.push({ shares: t.shares, price: t.price, fee: t.fee ?? 0 })
      } else if (t.action === 'SELL' && buyQueue.length > 0) {
        let remaining = Math.abs(t.shares)
        const sellFee = t.fee ?? 0

        while (remaining > 0 && buyQueue.length > 0) {
          const buy = buyQueue[0]
          const matched = Math.min(remaining, buy.shares)
          const pnl =
            matched * (t.price - buy.price) -
            sellFee * (matched / Math.abs(t.shares)) -
            buy.fee * (matched / buy.shares)
          totalPnl += pnl
          totalFees += sellFee * (matched / Math.abs(t.shares)) + buy.fee * (matched / buy.shares)
          if (pnl >= 0) wins++; else losses++
          buy.shares -= matched
          remaining -= matched
          if (buy.shares === 0) buyQueue.shift()
        }
      }
    }

    const total = wins + losses
    if (total === 0) continue
    rows.push({ ticker, wins, losses, total, winRate: wins / total, totalPnl, avgPnl: totalPnl / total, feesPaid: totalFees })
  }

  return rows.sort((a, b) => b.totalPnl - a.totalPnl)
}

export default function BacktestTrades() {
  const { data: histData } = useQuery({ queryKey: ['history'], queryFn: fetchHistory })
  const runs: BacktestRun[] = histData?.runs ?? []

  const defaultRunId = runs.length > 0 ? runs[runs.length - 1].run_id : 'latest'
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const runId = selectedRunId ?? defaultRunId

  const { data: trades = [], isLoading } = useQuery({
    queryKey: ['trades', runId],
    queryFn: () => fetchTrades(runId),
    enabled: !!runId,
  })

  const [filter, setFilter] = useState('')

  const buys = trades.filter(t => t.action === 'BUY').length
  const sells = trades.filter(t => t.action === 'SELL').length
  const totalFees = trades.reduce((s, t) => s + (t.fee ?? 0), 0)

  // Volume by ticker
  const volumeByTicker = Object.entries(
    trades.reduce((acc: Record<string, number>, t) => {
      acc[t.ticker] = (acc[t.ticker] ?? 0) + (t.value ?? 0)
      return acc
    }, {})
  )
    .map(([ticker, value]) => ({ ticker, value }))
    .sort((a, b) => b.value - a.value)

  // Trades per month
  const tradesByMonth = Object.entries(
    trades.reduce((acc: Record<string, number>, t) => {
      const m = t.date.slice(0, 7)
      acc[m] = (acc[m] ?? 0) + 1
      return acc
    }, {})
  )
    .map(([month, count]) => ({ month, count }))
    .sort((a, b) => a.month.localeCompare(b.month))

  const wlRows = computeWinLoss(trades)
  const overallWins = wlRows.reduce((s, r) => s + r.wins, 0)
  const overallLosses = wlRows.reduce((s, r) => s + r.losses, 0)
  const overallPnl = wlRows.reduce((s, r) => s + r.totalPnl, 0)
  const overallWr = overallWins + overallLosses > 0 ? overallWins / (overallWins + overallLosses) : 0

  const filteredTrades = filter
    ? trades.filter(t => t.ticker.includes(filter.toUpperCase()) || t.action.includes(filter.toUpperCase()))
    : trades

  if (isLoading) return <div className="text-gray-400 text-sm">Loading trades...</div>

  if (trades.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-2 text-gray-400">
        <p>No trade data for this run.</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-100">Backtest Trades</h1>

      {/* Run selector */}
      {runs.length > 0 && (
        <div className="card flex items-center gap-3">
          <label className="text-sm text-gray-400 whitespace-nowrap">Select run:</label>
          <select className="select text-sm flex-1" value={selectedRunId ?? defaultRunId}
            onChange={e => setSelectedRunId(e.target.value)}>
            {[...runs].reverse().map(r => (
              <option key={r.run_id} value={r.run_id}>
                {r.timestamp} — {r.params.n_stocks}s {r.params.years}y [{r.params.data_source}]
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-3">
        <div className="card">
          <p className="label">Total Trades</p>
          <p className="text-2xl font-bold text-gray-100">{trades.length}</p>
        </div>
        <div className="card">
          <p className="label">Buys / Sells</p>
          <p className="text-2xl font-bold">
            <span className="text-success">{buys}</span>
            <span className="text-gray-500"> / </span>
            <span className="text-danger">{sells}</span>
          </p>
        </div>
        <div className="card">
          <p className="label">Total Fees</p>
          <p className="text-2xl font-bold text-gray-100">{fmtVnd(totalFees)}</p>
        </div>
      </div>

      {/* Volume by ticker */}
      {volumeByTicker.length > 0 && (
        <div className="card">
          <h2 className="text-lg font-semibold mb-4 text-gray-200">Volume by Ticker</h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={volumeByTicker} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
              <XAxis dataKey="ticker" tick={{ fill: '#718096', fontSize: 11 }} />
              <YAxis tick={{ fill: '#718096', fontSize: 11 }} tickFormatter={fmtVnd} width={60} />
              <Tooltip contentStyle={{ background: '#1e2130', border: '1px solid #2d3748', borderRadius: 8 }}
                formatter={(v: number) => [fmtVnd(v), 'Total Value']} />
              <Bar dataKey="value" fill="#1B6CA8" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Trades per month */}
      {tradesByMonth.length > 0 && (
        <div className="card">
          <h2 className="text-lg font-semibold mb-4 text-gray-200">Trades per Month</h2>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={tradesByMonth} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
              <XAxis dataKey="month" tick={{ fill: '#718096', fontSize: 10 }} interval="preserveStartEnd" />
              <YAxis tick={{ fill: '#718096', fontSize: 11 }} width={30} />
              <Tooltip contentStyle={{ background: '#1e2130', border: '1px solid #2d3748', borderRadius: 8 }} />
              <Bar dataKey="count" fill="#1B6CA8" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Win/Loss summary */}
      {wlRows.length > 0 && (
        <div className="card space-y-4">
          <h2 className="text-lg font-semibold text-gray-200">Win / Loss by Stock</h2>
          <p className="text-xs text-gray-500">Each completed BUY → SELL round-trip counted as one trade. Open positions excluded.</p>

          <div className="grid grid-cols-4 gap-3">
            <div><p className="label">Overall Win Rate</p>
              <p className="text-xl font-bold text-gray-100">{(overallWr * 100).toFixed(0)}%</p></div>
            <div><p className="label">Total Wins</p>
              <p className="text-xl font-bold text-success">{overallWins}</p></div>
            <div><p className="label">Total Losses</p>
              <p className="text-xl font-bold text-danger">{overallLosses}</p></div>
            <div><p className="label">Total P&amp;L</p>
              <p className={`text-xl font-bold ${overallPnl >= 0 ? 'text-success' : 'text-danger'}`}>{fmtVnd(overallPnl)}</p></div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs uppercase border-b border-border">
                  {['Ticker','Wins','Losses','Total','Win %','Total P&L','Avg P&L','Fees'].map(h => (
                    <th key={h} className="py-2 pr-4 text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {wlRows.map(r => (
                  <tr key={r.ticker} className="border-b border-border/40 hover:bg-white/2">
                    <td className="py-2 pr-4 font-semibold text-gray-200">{r.ticker}</td>
                    <td className="py-2 pr-4 text-success">{r.wins}</td>
                    <td className="py-2 pr-4 text-danger">{r.losses}</td>
                    <td className="py-2 pr-4 text-gray-300">{r.total}</td>
                    <td className="py-2 pr-4 text-gray-300">{(r.winRate * 100).toFixed(0)}%</td>
                    <td className={`py-2 pr-4 font-semibold ${r.totalPnl >= 0 ? 'text-success' : 'text-danger'}`}>{fmtVnd(r.totalPnl)}</td>
                    <td className={`py-2 pr-4 ${r.avgPnl >= 0 ? 'text-success' : 'text-danger'}`}>{fmtVnd(r.avgPnl)}</td>
                    <td className="py-2 text-gray-400">{fmtVnd(r.feesPaid)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* P&L chart */}
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={wlRows} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
              <XAxis dataKey="ticker" tick={{ fill: '#718096', fontSize: 11 }} />
              <YAxis tick={{ fill: '#718096', fontSize: 11 }} tickFormatter={fmtVnd} width={60} />
              <Tooltip contentStyle={{ background: '#1e2130', border: '1px solid #2d3748', borderRadius: 8 }}
                formatter={(v: number) => [fmtVnd(v), 'P&L']} />
              <Bar dataKey="totalPnl" radius={[4, 4, 0, 0]}>
                {wlRows.map((r, i) => (
                  <Cell key={i} fill={r.totalPnl >= 0 ? '#3BB57A' : '#E85D24'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Full trade table */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-200">All Trades</h2>
          <input className="input text-sm w-48" placeholder="Filter ticker / action..."
            value={filter} onChange={e => setFilter(e.target.value)} />
        </div>
        <div className="overflow-x-auto max-h-96 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-card">
              <tr className="text-gray-500 text-xs uppercase border-b border-border">
                {['Date','Ticker','Action','Shares','Price','Value','Fee','Regime','Forecast'].map(h => (
                  <th key={h} className="py-2 pr-4 text-left">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...filteredTrades].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 200).map((t, i) => (
                <tr key={i} className="border-b border-border/30 hover:bg-white/2">
                  <td className="py-1.5 pr-4 text-gray-400">{t.date.slice(0, 10)}</td>
                  <td className="py-1.5 pr-4 font-semibold text-gray-200">{t.ticker}</td>
                  <td className={`py-1.5 pr-4 font-semibold ${t.action === 'BUY' ? 'text-success' : 'text-danger'}`}>{t.action}</td>
                  <td className="py-1.5 pr-4 font-mono text-gray-300">{t.shares?.toLocaleString()}</td>
                  <td className="py-1.5 pr-4 font-mono text-gray-300">{t.price?.toLocaleString()}</td>
                  <td className="py-1.5 pr-4 font-mono text-gray-300">{fmtVnd(t.value)}</td>
                  <td className="py-1.5 pr-4 font-mono text-gray-400">{fmtVnd(t.fee)}</td>
                  <td className="py-1.5 pr-4">
                    {t.regime && <span className={t.regime === 'BULL' ? 'tag-bull' : 'tag-bear'}>{t.regime}</span>}
                  </td>
                  <td className="py-1.5 font-mono text-gray-400">{t.forecast != null ? (t.forecast > 0 ? '+' : '') + t.forecast.toFixed(1) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {filteredTrades.length > 200 && (
            <p className="text-xs text-gray-500 mt-2 text-center">Showing 200 of {filteredTrades.length} trades</p>
          )}
        </div>
      </div>
    </div>
  )
}
