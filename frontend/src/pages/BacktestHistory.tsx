import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Trash2, AlertTriangle } from 'lucide-react'
import { fetchHistory, deleteRun, clearAllHistory } from '../api/client'
import type { BacktestRun } from '../types'
import { fmtPct, fmtNum } from '../utils/format'

export default function BacktestHistory() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['history'], queryFn: fetchHistory })
  const runs: BacktestRun[] = data?.runs ?? []

  const [confirmClear, setConfirmClear] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const deleteMut = useMutation({
    mutationFn: (runId: string) => deleteRun(runId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['history'] })
      setDeletingId(null)
    },
  })

  const clearMut = useMutation({
    mutationFn: clearAllHistory,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['history'] })
      setConfirmClear(false)
    },
  })

  if (isLoading) return <div className="text-gray-400 text-sm">Loading...</div>

  if (runs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-2 text-gray-400">
        <p>No history yet. Run at least one backtest to see results here.</p>
      </div>
    )
  }

  const carverRuns = [...runs].filter(r => (r.params?.strategy ?? 'carver') === 'carver').reverse()
  const swingRuns = [...runs].filter(r => r.params?.strategy === 'martin_luk').reverse()

  const renderDeleteBtn = (run: BacktestRun) =>
    deletingId === run.run_id ? (
      <div className="flex items-center gap-1">
        <button className="text-danger text-xs" onClick={() => deleteMut.mutate(run.run_id)}>Confirm</button>
        <span className="text-gray-500 text-xs">·</span>
        <button className="text-gray-400 text-xs" onClick={() => setDeletingId(null)}>Cancel</button>
      </div>
    ) : (
      <button onClick={() => setDeletingId(run.run_id)}
        className="text-gray-600 hover:text-danger transition-colors">
        <Trash2 size={14} />
      </button>
    )

  const renderCarverTable = (rows: BacktestRun[]) => (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-gray-500 text-xs uppercase border-b border-border">
          {['Run', 'Time', 'Stocks', 'Years', 'Source', 'CAGR', 'Sharpe', 'Max DD',
            'Win Rate', 'Cost/yr', 'Trades/mo', ''].map(h => (
            <th key={h} className="py-2 pr-4 text-left whitespace-nowrap">{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map(run => {
          const m = run.metrics ?? {} as any
          return (
            <tr key={run.run_id} className="border-b border-border/40 hover:bg-white/2">
              <td className="py-2 pr-4 font-mono text-xs text-gray-500">{run.run_id.slice(0, 8)}</td>
              <td className="py-2 pr-4 text-gray-300 whitespace-nowrap">{run.timestamp}</td>
              <td className="py-2 pr-4 text-gray-300">{run.params?.n_stocks}</td>
              <td className="py-2 pr-4 text-gray-300">{run.params?.years}</td>
              <td className="py-2 pr-4">
                <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                  run.params?.data_source === 'real' ? 'bg-success/20 text-success' : 'bg-gray-500/20 text-gray-400'
                }`}>{run.params?.data_source}</span>
              </td>
              <td className={`py-2 pr-4 font-semibold ${(m.cagr ?? 0) >= 0.045 ? 'text-success' : 'text-danger'}`}>{fmtPct(m.cagr)}</td>
              <td className={`py-2 pr-4 ${(m.sharpe ?? 0) >= 0.40 ? 'text-success' : 'text-danger'}`}>{fmtNum(m.sharpe)}</td>
              <td className={`py-2 pr-4 ${(m.max_drawdown ?? -1) > -0.30 ? 'text-success' : 'text-danger'}`}>{fmtPct(m.max_drawdown)}</td>
              <td className="py-2 pr-4 text-gray-300">{fmtPct(m.win_rate)}</td>
              <td className="py-2 pr-4 text-gray-300">{fmtPct(m.cost_drag_annual)}</td>
              <td className="py-2 pr-4 text-gray-300">{m.trades_per_month?.toFixed(0) ?? '—'}</td>
              <td className="py-2">{renderDeleteBtn(run)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )

  const renderSwingTable = (rows: BacktestRun[]) => (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-gray-500 text-xs uppercase border-b border-border">
          {['Run', 'Time', 'Stocks', 'Years', 'Source', 'CAGR', 'Sharpe', 'Expectancy', 'Max DD',
            'Win Rate', 'Avg Winner', ''].map(h => (
            <th key={h} className="py-2 pr-4 text-left whitespace-nowrap">{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map(run => {
          const m = run.metrics ?? {} as any
          return (
            <tr key={run.run_id} className="border-b border-border/40 hover:bg-white/2">
              <td className="py-2 pr-4 font-mono text-xs text-gray-500">{run.run_id.slice(0, 8)}</td>
              <td className="py-2 pr-4 text-gray-300 whitespace-nowrap">{run.timestamp}</td>
              <td className="py-2 pr-4 text-gray-300">{run.params?.n_stocks}</td>
              <td className="py-2 pr-4 text-gray-300">{run.params?.years}</td>
              <td className="py-2 pr-4">
                <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                  run.params?.data_source === 'real' ? 'bg-success/20 text-success' : 'bg-gray-500/20 text-gray-400'
                }`}>{run.params?.data_source}</span>
              </td>
              <td className={`py-2 pr-4 font-semibold ${(m.cagr ?? 0) >= 0.045 ? 'text-success' : 'text-danger'}`}>{fmtPct(m.cagr)}</td>
              <td className={`py-2 pr-4 ${(m.sharpe ?? 0) >= 0.40 ? 'text-success' : 'text-danger'}`}>{fmtNum(m.sharpe)}</td>
              <td className={`py-2 pr-4 ${(m.expectancy ?? 0) > 0.5 ? 'text-success' : 'text-danger'}`}>
                {m.expectancy != null ? `${m.expectancy.toFixed(2)}R` : '—'}
              </td>
              <td className={`py-2 pr-4 ${(m.max_drawdown ?? -1) > -0.30 ? 'text-success' : 'text-danger'}`}>{fmtPct(m.max_drawdown)}</td>
              <td className="py-2 pr-4 text-gray-300">{fmtPct(m.win_rate)}</td>
              <td className="py-2 pr-4 text-gray-300">
                {m.avg_winner_r != null ? `${m.avg_winner_r.toFixed(1)}R` : '—'}
              </td>
              <td className="py-2">{renderDeleteBtn(run)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-100">Backtest History</h1>
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-400">{runs.length} runs logged</span>
          {!confirmClear ? (
            <button className="btn-danger text-xs px-3 py-1.5" onClick={() => setConfirmClear(true)}>
              Clear All
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <AlertTriangle size={14} className="text-warning" />
              <span className="text-xs text-warning">Are you sure?</span>
              <button className="btn-danger text-xs px-3 py-1.5" onClick={() => clearMut.mutate()}>Yes, clear all</button>
              <button className="btn-secondary text-xs px-3 py-1.5" onClick={() => setConfirmClear(false)}>Cancel</button>
            </div>
          )}
        </div>
      </div>

      {/* Carver runs */}
      <div className="card overflow-x-auto">
        <h2 className="text-base font-semibold text-gray-200 mb-3">Carver — Momentum + Mean Reversion</h2>
        {carverRuns.length > 0 ? renderCarverTable(carverRuns) : (
          <p className="text-sm text-gray-500">No Carver backtest runs yet.</p>
        )}
      </div>

      {/* Martin Luk runs */}
      <div className="card overflow-x-auto">
        <h2 className="text-base font-semibold text-gray-200 mb-3">Martin Luk — Swing Breakout</h2>
        {swingRuns.length > 0 ? renderSwingTable(swingRuns) : (
          <p className="text-sm text-gray-500">No Martin Luk backtest runs yet.</p>
        )}
      </div>
    </div>
  )
}
