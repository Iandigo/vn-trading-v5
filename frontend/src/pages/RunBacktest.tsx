import { useState, useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Play, CheckCircle, XCircle, Loader, Trash2 } from 'lucide-react'
import { startBacktest, fetchJob, fetchUniverse, clearCache } from '../api/client'
import type { Job, Metrics, Strategy } from '../types'
import { fmtPct, fmtNum } from '../utils/format'

interface Props {
  onDone: () => void
}

const STAGE_LABELS: Record<string, string> = {
  queued:           'Queued...',
  generating_data:  'Generating mock data...',
  fetching_data:    'Fetching real market data (this takes a while)...',
  running_engine:   'Running backtest engine...',
  saving_results:   'Saving results...',
  done:             'Done!',
  error:            'Error occurred',
}

export default function RunBacktest({ onDone }: Props) {
  const qc = useQueryClient()

  const { data: universe = [] } = useQuery({ queryKey: ['universe'], queryFn: fetchUniverse })

  // Form state
  const [strategy, setStrategy] = useState<Strategy>('carver')
  const [nStocks, setNStocks] = useState(15)
  const [years, setYears] = useState(3)
  const [capital, setCapital] = useState(500_000_000)
  const [useReal, setUseReal] = useState(false)

  // Job tracking
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobDone, setJobDone] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [liveJob, setLiveJob] = useState<Job | null>(null)

  // Poll job status
  useEffect(() => {
    if (!jobId || jobDone) return

    pollRef.current = setInterval(async () => {
      try {
        const job = await fetchJob(jobId)
        setLiveJob(job)
        if (job.status === 'completed' || job.status === 'failed') {
          setJobDone(true)
          clearInterval(pollRef.current!)
          if (job.status === 'completed') {
            qc.invalidateQueries({ queryKey: ['history'] })
            qc.invalidateQueries({ queryKey: ['metrics'] })
            qc.invalidateQueries({ queryKey: ['equity'] })
          }
        }
      } catch {
        // Silently ignore poll errors
      }
    }, 2000)

    return () => clearInterval(pollRef.current!)
  }, [jobId, jobDone, qc])

  const runMut = useMutation({
    mutationFn: startBacktest,
    onSuccess: (id: string) => {
      setJobId(id)
      setJobDone(false)
      setLiveJob(null)
    },
  })

  const handleRun = () => {
    runMut.mutate({ n_stocks: nStocks, years, capital, use_real: useReal, strategy })
  }

  const isRunning = !!jobId && !jobDone

  const metrics: Metrics | null = liveJob?.result?.metrics ?? null

  const CARVER_SCORECARD = [
    { key: 'cagr' as keyof Metrics,         label: 'CAGR',       fmt: fmtPct, pass: (v: number) => v >= 0.045, target: '> 4.5%' },
    { key: 'sharpe' as keyof Metrics,       label: 'Sharpe',     fmt: fmtNum, pass: (v: number) => v >= 0.40,  target: '> 0.40' },
    { key: 'max_drawdown' as keyof Metrics, label: 'Max DD',     fmt: fmtPct, pass: (v: number) => v > -0.30,  target: '> -30%' },
    { key: 'cost_drag_annual' as keyof Metrics, label: 'Cost/yr', fmt: fmtPct, pass: (v: number) => v < 0.015, target: '< 1.5%' },
    { key: 'trades_per_month' as keyof Metrics, label: 'Trades/mo', fmt: (v: number) => v.toFixed(0), pass: (v: number) => v < 30, target: '< 30' },
    { key: 'win_rate' as keyof Metrics,     label: 'Win Rate',   fmt: fmtPct, pass: (v: number) => v >= 0.45,  target: '> 45%' },
  ]

  const MARTIN_LUK_SCORECARD = [
    { key: 'cagr' as keyof Metrics,         label: 'CAGR',        fmt: fmtPct, pass: (v: number) => v >= 0.045, target: '> 4.5%' },
    { key: 'sharpe' as keyof Metrics,       label: 'Sharpe',      fmt: fmtNum, pass: (v: number) => v >= 0.40,  target: '> 0.40' },
    { key: 'expectancy' as keyof Metrics,   label: 'Expectancy',  fmt: (v: number) => `${v.toFixed(2)}R`, pass: (v: number) => v > 0.5, target: '> 0.5R' },
    { key: 'max_drawdown' as keyof Metrics, label: 'Max DD',      fmt: fmtPct, pass: (v: number) => v > -0.30, target: '> -30%' },
    { key: 'avg_winner_r' as keyof Metrics, label: 'Avg Winner',  fmt: (v: number) => `${v.toFixed(1)}R`, pass: (v: number) => v >= 3.0, target: '> 3.0R' },
    { key: 'avg_loser_r' as keyof Metrics,  label: 'Avg Loser',   fmt: (v: number) => `${v.toFixed(1)}R`, pass: (v: number) => v > -1.5, target: '> -1.5R' },
    { key: 'win_rate' as keyof Metrics,     label: 'Win Rate',    fmt: fmtPct, pass: (v: number) => v >= 0.20, target: '> 20%' },
  ]

  const SCORECARD_QUICK = strategy === 'martin_luk' ? MARTIN_LUK_SCORECARD : CARVER_SCORECARD

  return (
    <div className="space-y-6 max-w-3xl">
      <h1 className="text-2xl font-bold text-gray-100">Run Backtest</h1>

      {/* Strategy selector */}
      <div className="card space-y-3">
        <h2 className="text-base font-semibold text-gray-200">Strategy</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <label className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
            strategy === 'carver' ? 'border-primary bg-primary/10' : 'border-border hover:border-gray-600'
          }`}>
            <input type="radio" name="strategy" checked={strategy === 'carver'}
              onChange={() => setStrategy('carver')} className="accent-primary mt-1" />
            <div>
              <p className="text-sm font-medium text-gray-200">Carver — Momentum + Mean Reversion</p>
              <p className="text-xs text-gray-500 mt-1">
                Cross-sectional momentum (55%) + IBS mean reversion (15%).
                Vol-based sizing with buffer zones. Monthly rebalance.
              </p>
            </div>
          </label>
          <label className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
            strategy === 'martin_luk' ? 'border-primary bg-primary/10' : 'border-border hover:border-gray-600'
          }`}>
            <input type="radio" name="strategy" checked={strategy === 'martin_luk'}
              onChange={() => setStrategy('martin_luk')} className="accent-primary mt-1" />
            <div>
              <p className="text-sm font-medium text-gray-200">Martin Luk — Swing Breakout</p>
              <p className="text-xs text-gray-500 mt-1">
                EMA alignment breakouts with 0.75% fixed risk per trade.
                Trailing stops + partial exits at 3R/5R. Adapted for VN30.
              </p>
            </div>
          </label>
        </div>
      </div>

      {/* Parameters form */}
      <div className="card space-y-5">
        <h2 className="text-base font-semibold text-gray-200">Parameters</h2>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {/* Number of stocks */}
          <div>
            <label className="label">Number of Stocks (1 – {universe.length || 30})</label>
            <input type="range" min={5} max={universe.length || 30} value={nStocks}
              onChange={e => setNStocks(+e.target.value)}
              className="w-full accent-primary" />
            <div className="flex justify-between items-center mt-1">
              <span className="text-xs text-gray-500">5</span>
              <span className="text-lg font-bold text-primary">{nStocks} stocks</span>
              <span className="text-xs text-gray-500">{universe.length || 30}</span>
            </div>
            {universe.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {universe.slice(0, nStocks).map(t => (
                  <span key={t} className="text-xs bg-primary/15 text-primary px-1.5 py-0.5 rounded font-medium">
                    {t.replace('.VN', '')}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Years */}
          <div>
            <label className="label">Backtest Period (years)</label>
            <input type="range" min={1} max={10} value={years}
              onChange={e => setYears(+e.target.value)}
              className="w-full accent-primary" />
            <div className="flex justify-between items-center mt-1">
              <span className="text-xs text-gray-500">1y</span>
              <span className="text-lg font-bold text-primary">{years} years</span>
              <span className="text-xs text-gray-500">10y</span>
            </div>
            <p className="text-xs text-gray-500 mt-1">
              Approx. date range:{' '}
              {new Date(Date.now() - years * 365.25 * 86400000).getFullYear()} – {new Date().getFullYear()}
            </p>
          </div>

          {/* Capital */}
          <div>
            <label className="label">Capital (VND)</label>
            <input type="number" className="input" value={capital}
              min={100_000_000} max={10_000_000_000} step={50_000_000}
              onChange={e => setCapital(+e.target.value)} />
            <p className="text-xs text-gray-500 mt-1">
              {capital >= 1e9 ? `${(capital / 1e9).toFixed(1)}B VND` : `${(capital / 1e6).toFixed(0)}M VND`}
              {capital < 200_000_000 && (
                <span className="text-warning"> — below 200M VND: lot-size rounding costs are significant</span>
              )}
            </p>
          </div>

          {/* Data source */}
          <div>
            <label className="label">Data Source</label>
            <div className="space-y-2 mt-1">
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="radio" name="source" checked={!useReal} onChange={() => setUseReal(false)}
                  className="accent-primary" />
                <div>
                  <p className="text-sm font-medium text-gray-200">Mock data</p>
                  <p className="text-xs text-gray-500">Synthetic VN-like data. Fast (~5s). Good for testing.</p>
                </div>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="radio" name="source" checked={useReal} onChange={() => setUseReal(true)}
                  className="accent-primary" />
                <div>
                  <p className="text-sm font-medium text-gray-200">Real data (yfinance)</p>
                  <p className="text-xs text-gray-500">Live market data. Takes 1–3 min depending on year count.</p>
                </div>
              </label>
            </div>
          </div>
        </div>

        {/* Run button + Delete Cache */}
        <div className="pt-2 border-t border-border flex items-center gap-3">
          <button className="btn-primary text-base px-8 py-3 flex items-center gap-2"
            onClick={handleRun} disabled={isRunning || runMut.isPending}>
            {isRunning ? (
              <><Loader size={16} className="animate-spin" /> Running...</>
            ) : (
              <><Play size={16} /> Run Backtest</>
            )}
          </button>
          <button
            className="px-4 py-3 text-sm rounded-lg border border-danger/40 text-danger hover:bg-danger/10 transition-colors flex items-center gap-2 disabled:opacity-50"
            disabled={isRunning}
            onClick={async () => {
              if (!confirm('Delete all cached market data? Next backtest will re-fetch everything from scratch.')) return
              try {
                const res = await clearCache()
                alert(`Deleted ${res.files_deleted} cached files. Data will be re-fetched on next run.`)
              } catch {
                alert('Failed to clear cache.')
              }
            }}
          >
            <Trash2 size={14} /> Delete Cache
          </button>
        </div>
      </div>

      {/* Progress */}
      {(isRunning || (liveJob && jobDone)) && (
        <div className="card space-y-3">
          <div className="flex items-center gap-3">
            {isRunning && <Loader size={18} className="animate-spin text-primary" />}
            {liveJob?.status === 'completed' && <CheckCircle size={18} className="text-success" />}
            {liveJob?.status === 'failed' && <XCircle size={18} className="text-danger" />}
            <div>
              <p className="text-sm font-medium text-gray-200">
                {liveJob ? STAGE_LABELS[liveJob.stage] ?? liveJob.stage : 'Starting...'}
              </p>
              {liveJob?.status === 'failed' && liveJob.error && (
                <p className="text-xs text-danger mt-1">{liveJob.error}</p>
              )}
            </div>
          </div>

          {/* Progress bar */}
          <div className="w-full bg-bg rounded-full h-2 overflow-hidden">
            <div className="h-2 rounded-full transition-all duration-500"
              style={{
                width: `${liveJob?.progress ?? 0}%`,
                background: liveJob?.status === 'failed' ? '#E85D24' : '#1B6CA8',
              }} />
          </div>
          <p className="text-xs text-gray-500">{liveJob?.progress ?? 0}% complete</p>
        </div>
      )}

      {/* Quick results */}
      {metrics && (
        <div className="card space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-success">
              Backtest Complete — Quick Scorecard
            </h2>
            <button className="btn-primary text-sm" onClick={onDone}>
              View Full Results
            </button>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {SCORECARD_QUICK.map(row => {
              const val = metrics[row.key] as number
              const passed = val != null && row.pass(val)
              return (
                <div key={row.key} className={`rounded-lg p-3 border ${passed ? 'border-success/30 bg-success/10' : 'border-danger/30 bg-danger/10'}`}>
                  <p className="text-xs text-gray-500">{row.label}</p>
                  <p className={`text-lg font-bold mt-1 ${passed ? 'text-success' : 'text-danger'}`}>
                    {val != null ? row.fmt(val) : '—'}
                  </p>
                  <p className="text-xs text-gray-500">{passed ? '✅' : '❌'} {row.target}</p>
                </div>
              )
            })}
          </div>

          <div className="text-xs text-gray-500">
            <span className="font-medium text-gray-400">{strategy === 'martin_luk' ? 'Martin Luk' : 'Carver'}</span>
            {' · '}Period: {metrics.start_date} → {metrics.end_date} ({metrics.n_years?.toFixed(1)}y) ·{' '}
            {metrics.n_trades} total trades
            {strategy === 'martin_luk' ? (
              <>{' · '}Avg hold: {(metrics as any).avg_holding_days?.toFixed(0) ?? '?'}d ·{' '}
              Max consec losses: {(metrics as any).max_consecutive_losses ?? '?'}</>
            ) : (
              <>{' · '}Bull regime {fmtPct(metrics.regime_pct_bull)} of time</>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
