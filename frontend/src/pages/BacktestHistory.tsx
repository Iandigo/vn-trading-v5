import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Trash2, AlertTriangle } from 'lucide-react'
import { fetchHistory, deleteRun, clearAllHistory } from '../api/client'
import type { BacktestRun } from '../types'

const fmtPct = (v: number | undefined) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)
const fmtNum = (v: number | undefined) => (v == null ? '—' : v.toFixed(2))

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

  const sorted = [...runs].reverse()

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

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs uppercase border-b border-border">
              {['Run', 'Time', 'Stocks', 'Years', 'Source', 'CAGR', 'Sharpe', 'Max DD',
                'Ann Vol', 'Win Rate', 'Cost/yr', 'Trades/mo', ''].map(h => (
                <th key={h} className="py-2 pr-4 text-left whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map(run => {
              const m = run.metrics ?? {}
              const cagr = m.cagr ?? null
              const sharpe = m.sharpe ?? null
              const dd = m.max_drawdown ?? null
              return (
                <tr key={run.run_id} className="border-b border-border/40 hover:bg-white/2">
                  <td className="py-2 pr-4 font-mono text-xs text-gray-500">{run.run_id.slice(0, 8)}</td>
                  <td className="py-2 pr-4 text-gray-300 whitespace-nowrap">{run.timestamp}</td>
                  <td className="py-2 pr-4 text-gray-300">{run.params?.n_stocks}</td>
                  <td className="py-2 pr-4 text-gray-300">{run.params?.years}</td>
                  <td className="py-2 pr-4">
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                      run.params?.data_source === 'real'
                        ? 'bg-success/20 text-success'
                        : 'bg-gray-500/20 text-gray-400'
                    }`}>
                      {run.params?.data_source}
                    </span>
                  </td>
                  <td className={`py-2 pr-4 font-semibold ${cagr != null && cagr >= 0.045 ? 'text-success' : 'text-danger'}`}>
                    {fmtPct(cagr)}
                  </td>
                  <td className={`py-2 pr-4 ${sharpe != null && sharpe >= 0.40 ? 'text-success' : 'text-danger'}`}>
                    {fmtNum(sharpe)}
                  </td>
                  <td className={`py-2 pr-4 ${dd != null && dd > -0.30 ? 'text-success' : 'text-danger'}`}>
                    {fmtPct(dd)}
                  </td>
                  <td className="py-2 pr-4 text-gray-300">{fmtPct(m.annual_vol)}</td>
                  <td className="py-2 pr-4 text-gray-300">{fmtPct(m.win_rate)}</td>
                  <td className="py-2 pr-4 text-gray-300">{fmtPct(m.cost_drag_annual)}</td>
                  <td className="py-2 pr-4 text-gray-300">{m.trades_per_month?.toFixed(0) ?? '—'}</td>
                  <td className="py-2">
                    {deletingId === run.run_id ? (
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
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Comparison insight */}
      {runs.length >= 2 && (() => {
        const last = runs[runs.length - 1]
        const prev = runs[runs.length - 2]
        const cagrDiff = ((last.metrics?.cagr ?? 0) - (prev.metrics?.cagr ?? 0)) * 100
        return (
          <div className="card bg-primary/10 border-primary/30">
            <p className="text-sm text-gray-300">
              <span className="font-semibold text-primary">Latest vs previous:</span>{' '}
              CAGR changed by{' '}
              <span className={cagrDiff >= 0 ? 'text-success font-semibold' : 'text-danger font-semibold'}>
                {cagrDiff >= 0 ? '+' : ''}{cagrDiff.toFixed(1)}%
              </span>{' '}
              ({prev.params?.n_stocks}s {prev.params?.years}y [{prev.params?.data_source}]{' '}
              → {last.params?.n_stocks}s {last.params?.years}y [{last.params?.data_source}])
            </p>
          </div>
        )
      })()}
    </div>
  )
}
